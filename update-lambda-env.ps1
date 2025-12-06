# Update Lambda environment variables from .env file

# Parse .env file
$env_vars = @{}
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#][^=]+)=(.*)$') {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim()
        $env_vars[$key] = $value
    }
}

# Build Lambda environment variables JSON
$lambda_env = @{
    "OPENAI_API_KEY" = $env_vars["OPENAI_API_KEY"]
    "CARTESIA_API_KEY" = $env_vars["CARTESIA_API_KEY"]
    "DEEPGRAM_API_KEY" = $env_vars["DEEPGRAM_API_KEY"]
    "REPLICATE_API_TOKEN" = $env_vars["REPLICATE_API_TOKEN"]
    "FREESOUND_API_KEY" = $env_vars["FREESOUND_API_KEY"]
    "DATABASE_URL" = $env_vars["DATABASE_URL"]
    "AWS_S3_BUCKET_NAME" = "june-story"
    "AWS_REGION" = "us-east-1"
    "FIREBASE_CREDENTIALS_PATH" = "./firebase-credentials.json"
    "FIREBASE_STORAGE_BUCKET" = $env_vars["FIREBASE_STORAGE_BUCKET"]
    "FIREBASE_WEB_API_KEY" = $env_vars["FIREBASE_WEB_API_KEY"]
}

# Convert to JSON string for AWS CLI
$json_string = ($lambda_env | ConvertTo-Json -Compress).Replace('"', '\"')

Write-Host "Updating Lambda environment variables..."
Write-Host ""

# Update Lambda function configuration
aws lambda update-function-configuration `
    --function-name story-generation-worker `
    --environment "Variables=$($lambda_env | ConvertTo-Json -Compress)" `
    --output json

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Success: Lambda environment variables updated"
} else {
    Write-Host ""
    Write-Host "Error: Failed to update Lambda environment variables"
    exit 1
}
