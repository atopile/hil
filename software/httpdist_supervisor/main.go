package main

import (
	"fmt"
	"log"
	"net"
	"net/http"
	"time"
)

const (
	programName   = "httpdist-supervisor"
	defaultApiUrl = "http://localhost:8000"
)

var apiUrl = getEnvOrDefault("HTTPDIST_API_URL", defaultApiUrl)
var ifaceNames = []string{"eth0", "en0", "wlan0"}

func getWorkerId() (string, error) {
	// get mac address
	interfaces, err := net.Interfaces()
	if err != nil {
		return "", fmt.Errorf("failed to get interfaces: %w", err)
	}

	for _, iface := range interfaces {
		for _, ifaceName := range ifaceNames {
			if iface.Name == ifaceName {
				macAddr := iface.HardwareAddr.String()
				macAddrNoColons := ""
				for _, c := range macAddr {
					if c != ':' {
						macAddrNoColons += string(c)
					}
				}
				return macAddrNoColons, nil
			}
		}
	}

	return "", fmt.Errorf("no matching interface found from: %v", ifaceNames)
}

func (c *ApiClient) registerWorker(workerId string) {
	jsonData := map[string]string{
		"worker_id": workerId,
	}

	responseJson, statusCode, err := c.httpPost("/worker/register", jsonData)
	if err != nil {
		log.Fatal(err)
	}
	if statusCode != http.StatusOK {
		log.Fatalf("failed to register worker: %s", responseJson["detail"])
	}

	fmt.Printf("Registered worker: %s\n", responseJson["worker_id"])
}

func sendHeartbeat(c *ApiClient, workerId string) {
	for {
		c.httpPost(fmt.Sprintf("/worker/%s/heartbeat", workerId), nil)
		time.Sleep(10 * time.Second)
	}
}

func pollForSession(c *ApiClient, workerId string) (*TestSession, error) {
	spinnerIdx := 0

	for {
		spinnerIdx = updateSpinner("Waiting for session", spinnerIdx)

		responseJson, statusCode, err := c.httpGet(fmt.Sprintf("/worker/%s/session", workerId))
		if err != nil {
			log.Fatal(err)
		}

		if statusCode == http.StatusNoContent {
			time.Sleep(1 * time.Second)
			continue
		} else if statusCode != http.StatusOK {
			log.Fatalf("failed to get session: %d (%s)", statusCode, responseJson["detail"])
		}

		sessionId := responseJson["session_id"].(string)

		clearSpinner()
		fmt.Printf("Received session: %s\n", sessionId)
		return &TestSession{WorkerId: workerId, SessionId: sessionId}, nil
	}
}

func runSession(apiClient *ApiClient, workerId string) {
	session, err := pollForSession(apiClient, workerId)
	if err != nil {
		log.Fatal(err)
	}

	err = session.prepareEnv(apiClient)
	if err != nil {
		log.Fatal(err)
	}
	defer session.cleanup()

	err = session.spawnWorker()
	if err != nil {
		log.Fatal(err)
	}
}

func main() {
	apiClient := &ApiClient{
		BaseUrl: apiUrl,
	}

	workerId, err := getWorkerId()
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("Starting worker with ID:", workerId)

	go sendHeartbeat(apiClient, workerId)

	// apiClient.registerWorker(workerId)

	for {
		runSession(apiClient, workerId)
	}
}
