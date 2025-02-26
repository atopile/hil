package main

// set worker_id
// register worker with server
// start a wait loop
// poll for session
// when given a session:
//  - pull env for session
//  - spawn pytest in session env

import (
	"fmt"
	"log"
	"net"
	"time"
)

const (
	ifaceName = "en0"
	apiUrl    = "http://localhost:8000"
)

func getWorkerId() (string, error) {
	// get mac address
	interfaces, err := net.Interfaces()
	if err != nil {
		return "", fmt.Errorf("failed to get interfaces: %w", err)
	}
	for _, iface := range interfaces {
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

	return "", fmt.Errorf("interface not found: %s", ifaceName)
}

func (c *ApiClient) registerWorker(workerId string) {
	jsonData := map[string]string{
		"worker_id": workerId,
	}

	responseBody := c.httpPost("/worker/register", jsonData)
	fmt.Println(string(responseBody))
}

func pollForSession(c *ApiClient, workerId string) {
	for {
		responseBody := c.httpGet(fmt.Sprintf("/worker/%s/session", workerId))
		fmt.Println(string(responseBody))
		time.Sleep(1 * time.Second)
	}
}

func main() {
	workerId, err := getWorkerId()
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("Starting worker with ID:", workerId)

	apiClient := &ApiClient{
		BaseUrl: apiUrl,
	}

	apiClient.registerWorker(workerId)
	pollForSession(apiClient, workerId)
}
