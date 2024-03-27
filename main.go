package main

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
)

func main() {
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// if GET request
		if r.Method == "GET" {
			fmt.Fprintf(w, "Hello World!")
		}
		// if POST request
		if r.Method == "POST" {
			// get UserName and Password from request
			r.ParseForm()
			UserName := r.FormValue("UserName")
			Password := r.FormValue("Password")

			fmt.Println("UserName: ", UserName)
			fmt.Println("Password: ", Password)

			// target URL "https://portal.aiub.edu"
			// Login with UserName and Password to the target URL and scrape the html content
			response, err := scrapeContent(UserName, Password)
			if err != nil {
				http.Error(w, "Error scraping content: "+err.Error(), http.StatusInternalServerError)
				return
			}
			fmt.Fprintf(w, "Response from %s: %s", response.TargetURL, response.Body)
		}
	})

	port := os.Getenv("PORT")
	if port == "" {
		port = "3000"
	}

	fmt.Printf("Server running on port %s\n", port)
	http.ListenAndServe(":"+port, nil)
}

// ScrapeResponse represents the response from scraping content
type ScrapeResponse struct {
	TargetURL string
	Body      string
}

func scrapeContent(username, password string) (*ScrapeResponse, error) {
	// Login to the target URL and scrape HTML content
	targetURL := "https://portal.aiub.edu"
	loginData := strings.NewReader("UserName=" + username + "&Password=" + password)

	resp, err := http.Post(targetURL, "application/x-www-form-urlencoded", loginData)
	if err != nil {
		return nil, fmt.Errorf("error sending POST request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("error reading response body: %w", err)
	}

	return &ScrapeResponse{
		TargetURL: targetURL,
		Body:      string(body),
	}, nil
}
