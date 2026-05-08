param(
    [string]$OutputDir = "data",
    [int]$TopRepositories = 200,
    [int]$MinPrs = 100,
    [int]$MaxPrsPerRepo = 0,
    [string]$Language,
    [string[]]$Repositories
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Net.Http
$script:HttpClient = New-Object System.Net.Http.HttpClient
$script:HttpClient.Timeout = [TimeSpan]::FromSeconds(120)

function Get-GitHubToken {
    if ($env:GITHUB_TOKEN) {
        return $env:GITHUB_TOKEN
    }
    throw "A variavel de ambiente GITHUB_TOKEN nao foi definida."
}

function New-GitHubHeaders {
    $token = Get-GitHubToken
    return @{
        Authorization         = "Bearer $token"
        Accept                = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "User-Agent"          = "LabExperimentacao-3"
    }
}

function Start-RateLimitWait {
    param([System.Net.WebHeaderCollection]$Headers)

    $remaining = $Headers["X-RateLimit-Remaining"]
    $reset = $Headers["X-RateLimit-Reset"]
    if ($remaining -eq "0" -and $reset) {
        $resetUnix = [int64]$reset
        $nowUnix = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $waitSeconds = [Math]::Max(($resetUnix - $nowUnix + 1), 1)
        Write-Host "Limite da API atingido. Aguardando $waitSeconds segundos..."
        Start-Sleep -Seconds $waitSeconds
    }
}

function Invoke-GitHubRequest {
    param(
        [string]$Url,
        [hashtable]$Query = @{}
    )

    $headers = New-GitHubHeaders
    $queryString = ""
    if ($Query.Count -gt 0) {
        $pairs = foreach ($key in $Query.Keys) {
            $encodedKey = [System.Uri]::EscapeDataString([string]$key)
            $encodedValue = [System.Uri]::EscapeDataString([string]$Query[$key])
            "$encodedKey=$encodedValue"
        }
        $queryString = "?" + ($pairs -join "&")
    }

    $fullUrl = if ($Url.StartsWith("http")) { "$Url$queryString" } else { "https://api.github.com$Url$queryString" }

    $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $fullUrl)
    foreach ($key in $headers.Keys) {
        [void]$request.Headers.TryAddWithoutValidation($key, [string]$headers[$key])
    }

    $response = $script:HttpClient.SendAsync($request).GetAwaiter().GetResult()
    if (-not $response.IsSuccessStatusCode) {
        if ([int]$response.StatusCode -eq 403) {
            $headerBag = New-Object System.Net.WebHeaderCollection
            foreach ($header in $response.Headers) {
                $headerBag[$header.Key] = ($header.Value -join ",")
            }
            Start-RateLimitWait -Headers $headerBag
            $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $fullUrl)
            foreach ($key in $headers.Keys) {
                [void]$request.Headers.TryAddWithoutValidation($key, [string]$headers[$key])
            }
            $response = $script:HttpClient.SendAsync($request).GetAwaiter().GetResult()
        }
    }

    if (-not $response.IsSuccessStatusCode) {
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        throw "Erro HTTP $([int]$response.StatusCode) em $fullUrl : $body"
    }

    $responseText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $parsedContent = $responseText | ConvertFrom-Json
    $responseHeaders = New-Object System.Net.WebHeaderCollection
    foreach ($header in $response.Headers) {
        $responseHeaders[$header.Key] = ($header.Value -join ",")
    }

    return [pscustomobject]@{
        Content = $parsedContent
        Headers = $responseHeaders
    }
}

function Get-PaginatedItems {
    param(
        [string]$Path,
        [hashtable]$Query = @{}
    )

    $items = New-Object System.Collections.Generic.List[object]
    $nextUrl = $Path
    $currentQuery = @{}
    foreach ($key in $Query.Keys) {
        $currentQuery[$key] = $Query[$key]
    }
    if (-not $currentQuery.ContainsKey("per_page")) {
        $currentQuery["per_page"] = 100
    }

    while ($nextUrl) {
        $response = Invoke-GitHubRequest -Url $nextUrl -Query $currentQuery
        $content = $response.Content
        if ($content -is [System.Array]) {
            foreach ($item in $content) {
                [void]$items.Add($item)
            }
        } else {
            throw "Resposta paginada inesperada em $nextUrl"
        }

        $linkHeader = $response.Headers["Link"]
        $nextUrl = $null
        if ($linkHeader) {
            $matches = [regex]::Matches($linkHeader, '<([^>]+)>;\s*rel="next"')
            if ($matches.Count -gt 0) {
                $nextUrl = $matches[0].Groups[1].Value
            }
        }

        $currentQuery = @{}
    }

    return $items
}

function Get-PopularRepositories {
    param(
        [int]$Limit,
        [string]$Language
    )

    $repositories = New-Object System.Collections.Generic.List[object]
    $page = 1

    while ($repositories.Count -lt $Limit) {
        $query = "stars:>1 archived:false mirror:false"
        if ($Language) {
            $query += " language:$Language"
        }

        $response = Invoke-GitHubRequest -Url "/search/repositories" -Query @{
            q        = $query
            sort     = "stars"
            order    = "desc"
            per_page = 100
            page     = $page
        }

        $payload = $response.Content
        if (-not $payload.items -or $payload.items.Count -eq 0) {
            break
        }

        foreach ($repo in $payload.items) {
            [void]$repositories.Add($repo)
            if ($repositories.Count -ge $Limit) {
                break
            }
        }
        $page += 1
    }

    return $repositories
}

function Test-IsBot {
    param([string]$Login)

    if (-not $Login) {
        return $false
    }
    $lower = $Login.ToLowerInvariant()
    return $lower.Contains("[bot]") -or $lower.EndsWith("-bot")
}

function Get-ClosedPrCount {
    param(
        [string]$Owner,
        [string]$Repo
    )

    $response = Invoke-GitHubRequest -Url "/search/issues" -Query @{
        q        = "repo:$Owner/$Repo is:pr is:closed"
        per_page = 1
    }
    $payload = $response.Content
    return [int]$payload.total_count
}

function Invoke-ForPullRequests {
    param(
        [string]$Owner,
        [string]$Repo,
        [int]$Limit,
        [scriptblock]$Action
    )

    $nextUrl = "/repos/$Owner/$Repo/pulls"
    $currentQuery = @{
        state     = "closed"
        sort      = "updated"
        direction = "desc"
        per_page  = 100
    }
    $processed = 0

    while ($nextUrl) {
        $response = Invoke-GitHubRequest -Url $nextUrl -Query $currentQuery
        $content = $response.Content
        if ($content -is [System.Array]) {
            foreach ($item in $content) {
                & $Action $item
                $processed += 1
                if ($Limit -gt 0 -and $processed -ge $Limit) {
                    return
                }
            }
        } else {
            throw "Resposta inesperada ao listar PRs de $Owner/$Repo"
        }

        $linkHeader = $response.Headers["Link"]
        $nextUrl = $null
        if ($linkHeader) {
            $matches = [regex]::Matches($linkHeader, '<([^>]+)>;\s*rel="next"')
            if ($matches.Count -gt 0) {
                $nextUrl = $matches[0].Groups[1].Value
            }
        }
        $currentQuery = @{}
    }
}

function Get-UniqueParticipantCount {
    param(
        $PullRequest,
        [object[]]$Reviews,
        [object[]]$IssueComments,
        [object[]]$ReviewComments
    )

    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    if ($PullRequest.user.login) {
        [void]$set.Add($PullRequest.user.login)
    }
    foreach ($item in @($Reviews) + @($IssueComments) + @($ReviewComments)) {
        if ($item.user.login) {
            [void]$set.Add($item.user.login)
        }
    }
    return $set.Count
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Save-Progress {
    param(
        [System.Collections.Generic.List[object]]$RepositoriesData,
        [System.Collections.Generic.List[object]]$DatasetData,
        [string]$BaseDir
    )

    $RepositoriesData | Export-Csv -Path (Join-Path $BaseDir "selected_repositories.csv") -NoTypeInformation -Encoding UTF8
    $DatasetData | Export-Csv -Path (Join-Path $BaseDir "pull_requests_dataset.csv") -NoTypeInformation -Encoding UTF8
}

Ensure-Directory -Path $OutputDir

$selectedRepositories = New-Object System.Collections.Generic.List[object]
$datasetRows = New-Object System.Collections.Generic.List[object]

$targetRepositories =
if ($Repositories -and $Repositories.Count -gt 0) {
    $repoObjects = New-Object System.Collections.Generic.List[object]
    foreach ($fullName in $Repositories) {
        $parts = $fullName.Split("/")
        if ($parts.Count -ne 2) {
            throw "Repositorio invalido: $fullName"
        }
        $owner = $parts[0]
        $repo = $parts[1]
        $response = Invoke-GitHubRequest -Url "/repos/$owner/$repo"
        [void]$repoObjects.Add($response.Content)
    }
    @($repoObjects.ToArray())
} else {
    @(Get-PopularRepositories -Limit $TopRepositories -Language $Language)
}

foreach ($repository in $targetRepositories) {
    $fullName = [string]$repository.full_name
    $parts = $fullName.Split("/")
    if ($parts.Count -ne 2) {
        Write-Warning "Repositorio ignorado por full_name invalido: $fullName"
        continue
    }
    $owner = $parts[0]
    $repo = $parts[1]

    try {
        $closedPrCount = Get-ClosedPrCount -Owner $owner -Repo $repo
        if ($closedPrCount -lt $MinPrs) {
            continue
        }

        [void]$selectedRepositories.Add([pscustomobject]@{
            full_name = $repository.full_name
            stars     = $repository.stargazers_count
            language  = $repository.language
            html_url  = $repository.html_url
        })
        Save-Progress -RepositoriesData $selectedRepositories -DatasetData $datasetRows -BaseDir $OutputDir

        $script:processedPrs = 0
        Invoke-ForPullRequests -Owner $owner -Repo $repo -Limit $MaxPrsPerRepo -Action {
            param($pr)
            $script:processedPrs += 1

            $reviews = @(Get-PaginatedItems -Path "/repos/$owner/$repo/pulls/$($pr.number)/reviews")
            $humanReviews = @($reviews | Where-Object { -not (Test-IsBot -Login $_.user.login) })
            if ($humanReviews.Count -eq 0) {
                if (($script:processedPrs % 25) -eq 0) {
                    Write-Host "Repositorio $fullName | PRs analisados: $script:processedPrs | validos: $($datasetRows.Count)"
                    Save-Progress -RepositoriesData $selectedRepositories -DatasetData $datasetRows -BaseDir $OutputDir
                }
                return
            }

            $createdAt = [DateTimeOffset]::Parse($pr.created_at)
            $finishedRaw = if ($pr.merged_at) { $pr.merged_at } else { $pr.closed_at }
            if (-not $finishedRaw) {
                return
            }
            $finishedAt = [DateTimeOffset]::Parse($finishedRaw)
            $analysisHours = ($finishedAt - $createdAt).TotalHours
            if ($analysisHours -lt 1) {
                return
            }

            $issueComments = @(Get-PaginatedItems -Path "/repos/$owner/$repo/issues/$($pr.number)/comments")
            $reviewComments = @(Get-PaginatedItems -Path "/repos/$owner/$repo/pulls/$($pr.number)/comments")
            $files = @(Get-PaginatedItems -Path "/repos/$owner/$repo/pulls/$($pr.number)/files")

            $reviewApprovals = @($humanReviews | Where-Object { $_.state -eq "APPROVED" }).Count
            $reviewChangeRequests = @($humanReviews | Where-Object { $_.state -eq "CHANGES_REQUESTED" }).Count
            $reviewCommentsOnly = @($humanReviews | Where-Object { $_.state -eq "COMMENTED" }).Count
            $descriptionLength = if ($pr.body) { $pr.body.Length } else { 0 }

            [void]$datasetRows.Add([pscustomobject]@{
                repository_full_name = $repository.full_name
                repository_stars = $repository.stargazers_count
                repository_language = $repository.language
                pull_number = $pr.number
                pull_state = $(if ($pr.merged_at) { "merged" } else { "closed" })
                merged_flag = $(if ($pr.merged_at) { 1 } else { 0 })
                created_at = $pr.created_at
                closed_or_merged_at = $finishedRaw
                analysis_time_hours = [Math]::Round($analysisHours, 4)
                analysis_time_days = [Math]::Round(($finishedAt - $createdAt).TotalDays, 4)
                files_changed = $files.Count
                additions = $pr.additions
                deletions = $pr.deletions
                changed_lines_total = ($pr.additions + $pr.deletions)
                description_length = $descriptionLength
                participants_count = Get-UniqueParticipantCount -PullRequest $pr -Reviews $humanReviews -IssueComments $issueComments -ReviewComments $reviewComments
                issue_comments_count = $issueComments.Count
                review_comments_count = $reviewComments.Count
                comments_total = ($issueComments.Count + $reviewComments.Count)
                reviews_count = $humanReviews.Count
                review_approvals = $reviewApprovals
                review_change_requests = $reviewChangeRequests
                review_comments_only = $reviewCommentsOnly
                author_login = $pr.user.login
                url = $pr.html_url
            })
            if (($script:processedPrs % 10) -eq 0) {
                Write-Host "Repositorio $fullName | PRs analisados: $script:processedPrs | validos: $($datasetRows.Count)"
                Save-Progress -RepositoriesData $selectedRepositories -DatasetData $datasetRows -BaseDir $OutputDir
            }
        }

        Write-Host "Repositorio processado: $fullName | PRs validos acumulados: $($datasetRows.Count)"
        Save-Progress -RepositoriesData $selectedRepositories -DatasetData $datasetRows -BaseDir $OutputDir
    } catch {
        Write-Warning "Falha ao processar ${fullName}: $($_.Exception.Message)"
        Save-Progress -RepositoriesData $selectedRepositories -DatasetData $datasetRows -BaseDir $OutputDir
    }
}
Save-Progress -RepositoriesData $selectedRepositories -DatasetData $datasetRows -BaseDir $OutputDir

Write-Host "Repositorios selecionados: $($selectedRepositories.Count)"
Write-Host "PRs coletados: $($datasetRows.Count)"
