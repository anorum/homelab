# IRSA on k3s (IAM Roles for Service Accounts)

Pods in this cluster can assume AWS IAM roles with no stored credentials.
The mechanism is the same one EKS uses, wired by hand because k3s has none of the EKS glue.

## How it works

1. The k3s apiserver issues ServiceAccount tokens signed by the cluster's own key, with a configurable issuer and audience.
2. The cluster's OIDC discovery documents (`/.well-known/openid-configuration` and the JWKS) are published to a public S3 bucket, because AWS must be able to fetch them anonymously.
3. An IAM OIDC identity provider in the AWS account points at that bucket URL.
4. A pod mounts a projected ServiceAccount token with audience `sts.amazonaws.com`; the AWS SDK exchanges it via `sts:AssumeRoleWithWebIdentity` and refreshes it on its own.

No secret exists anywhere in this flow.
The trust is the cluster's signing key, published as a public JWKS.

## Cluster-side configuration

The k3s apiserver runs with these flags (set in the k3s config on swagman-1):

```
--kube-apiserver-arg=service-account-issuer=https://anorum-swagman-oidc.s3.us-west-2.amazonaws.com
--kube-apiserver-arg=service-account-jwks-uri=https://anorum-swagman-oidc.s3.us-west-2.amazonaws.com/openid/v1/jwks
```

The discovery documents are republished to the bucket whenever the cluster's signing key changes (in practice: after a k3s reinstall, not in normal operation):

```sh
kubectl get --raw /.well-known/openid-configuration | aws s3 cp - s3://anorum-swagman-oidc/.well-known/openid-configuration
kubectl get --raw /openid/v1/jwks | aws s3 cp - s3://anorum-swagman-oidc/openid/v1/jwks
```

The bucket name is public by design; OIDC discovery cannot work otherwise.
Account IDs and role ARNs never live in this repo.

## Per-project recipe

Each workload gets its own role, scoped to exactly what it touches.
The trust policy binds the role to one ServiceAccount:

```json
{
  "Effect": "Allow",
  "Principal": { "Federated": "arn:aws:iam::<account>:oidc-provider/anorum-swagman-oidc.s3.us-west-2.amazonaws.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "anorum-swagman-oidc.s3.us-west-2.amazonaws.com:aud": "sts.amazonaws.com",
      "anorum-swagman-oidc.s3.us-west-2.amazonaws.com:sub": "system:serviceaccount:<namespace>:<serviceaccount>"
    }
  }
}
```

Because there is no EKS mutating webhook, each pod spec wires the credentials by hand:

```yaml
env:
  - name: AWS_ROLE_ARN
    value: <role arn, substituted at deploy time or held in the project repo>
  - name: AWS_WEB_IDENTITY_TOKEN_FILE
    value: /var/run/secrets/eks.amazonaws.com/serviceaccount/token
  - name: AWS_REGION
    value: us-west-2
volumes:
  - name: aws-token
    projected:
      sources:
        - serviceAccountToken:
            audience: sts.amazonaws.com
            expirationSeconds: 3600
            path: token
```

The audience must match the trust policy exactly or STS rejects the token.

## Current consumers

| Role | ServiceAccount | Scope |
| --- | --- | --- |
| blockade-poller | blockade/poller | write frames and manifests to its bucket |
| blockade-detector | blockade/detector | read frames and references only |
| blockade-flink | blockade/flink | read/write its checkpoint prefix only |

Roles live in AWS and are created imperatively by their projects; this document is the contract, not the automation.
