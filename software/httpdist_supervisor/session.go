package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

type TestSession struct {
	WorkerId  string
	SessionId string
	EnvDir    string
}

func (session *TestSession) prepareEnv(apiClient *ApiClient) error {
	tempDir, err := os.MkdirTemp("", programName)
	if err != nil {
		return fmt.Errorf("failed to createTempDir(): %w", err)
	}

	zipPath := filepath.Join(tempDir, "env.zip")
	zipFile, err := os.Create(zipPath)
	if err != nil {
		return fmt.Errorf("failed to create zip file: %w", err)
	}
	defer zipFile.Close()

	zipContent, statusCode, err := apiClient.httpGetRaw(fmt.Sprintf("/worker/%s/session/%s/env", session.WorkerId, session.SessionId))
	if err != nil {
		return fmt.Errorf("failed to download env.zip: %w", err)
	}
	if statusCode != 200 {
		return fmt.Errorf("failed to download env.zip: status code %d", statusCode)
	}

	_, err = zipFile.Write(zipContent)
	if err != nil {
		return fmt.Errorf("failed to write zip file: %w", err)
	}
	zipFile.Close()

	envDir := filepath.Join(tempDir, "env")
	err = os.MkdirAll(envDir, 0755)
	if err != nil {
		return fmt.Errorf("failed to create env directory: %w", err)
	}

	err = extractZip(zipPath, envDir)
	if err != nil {
		return fmt.Errorf("failed to extract zip file: %w", err)
	}

	session.EnvDir = envDir
	return nil
}

func (session *TestSession) spawnWorker() error {
	// TOOD: pytest args
	cmd := exec.Command(
		"uv",
		"run",
		"--isolated",
		"pytest",
		"--httpdist-worker-id",
		session.WorkerId,
		"--httpdist-session-id",
		session.SessionId,
	)

	cmd.Dir = session.EnvDir

	start := time.Now()
	cmd.Run()

	elapsed := time.Since(start)
	fmt.Printf("Executed test session %s in %.2fs\n", session.SessionId, elapsed.Seconds())

	return nil
}

func (session *TestSession) cleanup() error {
	os.RemoveAll(session.EnvDir)
	return nil
}
