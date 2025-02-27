package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type ApiClient struct {
	BaseUrl string
}

func (c *ApiClient) httpGetRaw(path string) ([]byte, int, error) {
	request, err := http.NewRequest("GET", c.BaseUrl+path, nil)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to create request: %w", err)
	}

	client := &http.Client{}
	response, err := client.Do(request)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to send request: %w", err)
	}

	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to read response body: %w", err)
	}

	return body, response.StatusCode, nil
}

func (c *ApiClient) httpGet(path string) (map[string]interface{}, int, error) {
	body, statusCode, err := c.httpGetRaw(path)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to get raw response: %w", err)
	}

	if statusCode == http.StatusNoContent {
		return nil, statusCode, nil
	}

	var jsonResponse map[string]interface{}
	err = json.Unmarshal(body, &jsonResponse)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to unmarshal response body: %w", err)
	}

	return jsonResponse, statusCode, nil
}

func (c *ApiClient) httpPostRaw(path string, jsonData map[string]string) ([]byte, int, error) {
	jsonBytes, err := json.Marshal(jsonData)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to marshal json: %w", err)
	}

	request, err := http.NewRequest("POST", c.BaseUrl+path, bytes.NewBuffer(jsonBytes))
	if err != nil {
		return nil, 0, fmt.Errorf("failed to create request: %w", err)
	}

	client := &http.Client{}
	response, err := client.Do(request)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to send request: %w", err)
	}

	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to read response body: %w", err)
	}

	return responseBody, response.StatusCode, nil
}

func (c *ApiClient) httpPost(path string, jsonData map[string]string) (map[string]interface{}, int, error) {
	body, statusCode, err := c.httpPostRaw(path, jsonData)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to post raw response: %w", err)
	}

	var jsonResponse map[string]interface{}
	err = json.Unmarshal(body, &jsonResponse)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to unmarshal response body: %w", err)
	}

	return jsonResponse, statusCode, nil
}
