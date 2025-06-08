#!/bin/bash

# Generate secure random values
SECRET_KEY=$(openssl rand -base64 50)
POSTGRES_PASSWORD=$(openssl rand -base64 24)
REDIS_PASSWORD=$(openssl rand -base64 24)

# Replace placeholders in the secrets.yaml file
sed -i '' "s|PleaseGenerateASecureKeyAndReplaceThis|$SECRET_KEY|g" secrets.yaml
sed -i '' "s|GenerateASecurePasswordAndReplaceThis|$POSTGRES_PASSWORD|g" secrets.yaml
sed -i '' "s|GenerateADifferentSecurePasswordAndReplaceThis|$REDIS_PASSWORD|g" secrets.yaml

echo "✅ Secrets generated and updated in secrets.yaml"
echo "⚠️ Remember to add secrets.yaml to your .gitignore!"
