resource "aws_iam_user" "backup" {
  name = "homelab-backup"
}

resource "aws_iam_user_policy" "backup_s3" {
  name = "homelab-backup-s3"
  user = aws_iam_user.backup.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowS3BackupOperations"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:AbortMultipartUpload",
        ]
        Resource = [
          "arn:aws:s3:::anorum-homelab",
          "arn:aws:s3:::anorum-homelab/*",
        ]
      }
    ]
  })
}

resource "aws_iam_access_key" "backup" {
  user = aws_iam_user.backup.name
}
