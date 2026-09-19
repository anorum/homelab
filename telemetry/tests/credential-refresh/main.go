// This acceptance probe retains one SDK client through real session expiration.
// It never prints credentials, identity ARNs, or raw provider errors.
package main

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sts"
)

func fail(stage string) {
	_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"stage": stage, "success": false})
	os.Exit(1)
}

func main() {
	role := strings.Split(os.Getenv("EXPECTED_AWS_ROLE_ARN"), ":")
	if len(role) != 6 || !strings.HasPrefix(role[5], "role/") {
		fail("expected_role_configuration")
	}
	account := role[4]
	roleName := strings.TrimPrefix(role[5], "role/")
	prefix := "arn:" + role[1] + ":sts::" + account + ":assumed-role/" + roleName + "/"
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	defer cancel()
	// The SDK's default command builder forwards helper stderr through os.Stderr.
	// Keep its normal provider/cache behavior while suppressing raw diagnostics.
	discarded, err := os.OpenFile(os.DevNull, os.O_WRONLY, 0)
	if err != nil {
		fail("suppress_helper_diagnostics")
	}
	defer discarded.Close()
	os.Stderr = discarded
	cfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		fail("load_sdk_configuration")
	}
	first, err := cfg.Credentials.Retrieve(ctx)
	if err != nil {
		fail("initial_credentials")
	}
	remaining := time.Until(first.Expires)
	if !strings.Contains(first.Source, "ProcessProvider") || !first.CanExpire || first.SessionToken == "" || remaining < 14*time.Minute || remaining > 16*time.Minute {
		fail("process_provider_and_session_duration")
	}
	client := sts.NewFromConfig(cfg)
	_ = json.NewEncoder(os.Stdout).Encode(map[string]any{
		"stage": "initial_credentials", "success": true, "source": first.Source,
		"expires": first.Expires.UTC().Format(time.RFC3339),
	})
	for {
		current, err := cfg.Credentials.Retrieve(ctx)
		if err != nil {
			fail("retrieve_cached_credentials")
		}
		callCtx, stop := context.WithTimeout(ctx, 20*time.Second)
		identity, err := client.GetCallerIdentity(callCtx, &sts.GetCallerIdentityInput{})
		stop()
		if err != nil {
			fail("sts_get_caller_identity")
		}
		if identity.Account == nil || *identity.Account != account || identity.Arn == nil || !strings.HasPrefix(*identity.Arn, prefix) {
			fail("device_role_identity")
		}
		if current.AccessKeyID != first.AccessKeyID {
			if !current.Expires.After(first.Expires) || time.Now().Before(first.Expires) {
				fail("expiration_driven_refresh")
			}
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{
				"stage": "expiration_driven_refresh", "success": true,
				"credentials_changed": true, "identity_matches": true,
				"expires": current.Expires.UTC().Format(time.RFC3339),
			})
			return
		}
		select {
		case <-ctx.Done():
			fail("refresh_timeout")
		case <-time.After(30 * time.Second):
		}
	}
}
