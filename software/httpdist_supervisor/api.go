package main

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"
)

type ApiClient struct {
	BaseUrl string
}

func (c *ApiClient) httpGet(path string) []byte {
	request, err := http.NewRequest("GET", c.BaseUrl+path, nil)
	if err != nil {
		log.Fatal(err)
	}

	client := &http.Client{}
	response, err := client.Do(request)
	if err != nil {
		log.Fatal(err)
	}

	body, err := io.ReadAll(response.Body)
	if err != nil {
		log.Fatal(err)
	}

	return body
}

func (c *ApiClient) httpPost(path string, jsonData map[string]string) []byte {
	jsonBytes, err := json.Marshal(jsonData)
	if err != nil {
		log.Fatal(err)
	}

	request, err := http.NewRequest("POST", c.BaseUrl+path, bytes.NewBuffer(jsonBytes))
	if err != nil {
		log.Fatal(err)
	}

	client := &http.Client{}
	response, err := client.Do(request)
	if err != nil {
		log.Fatal(err)
	}

	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		log.Fatal(err)
	}

	return responseBody
}
