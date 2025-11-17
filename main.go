package main

import (
	"bufio"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"math/rand"
	"os"
	"os/signal"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/chromedp/chromedp"
	_ "github.com/mattn/go-sqlite3"
)

const dbFileName = "leads_greece_2025.sqlite"

type Config struct {
	OutputFilename     string   `json:"output_filename"`
	SearchTerm         string   `json:"search_term"`
	Locations          []string `json:"locations"`
	MaxResultsPerQuery int      `json:"max_results_per_query"`
	PhoneMinDigits     int      `json:"phone_min_digits"`
	Headless           bool     `json:"headless"`
	UseThreading       bool     `json:"use_threading"`
	MaxThreadWorkers   int      `json:"max_thread_workers"`
	ScrollPauseTime    float64  `json:"scroll_pause_time"`
	MaxScrollAttempts  int      `json:"max_scroll_attempts"`
}

var defaultConfig = Config{
	OutputFilename:     "recipients.csv",
	SearchTerm:         "",
	Locations:          []string{},
	MaxResultsPerQuery: 0,
	PhoneMinDigits:     10,
	Headless:           true,
	UseThreading:       false,
	MaxThreadWorkers:   3,
	ScrollPauseTime:    2,
	MaxScrollAttempts:  20,
}

type Business struct {
	ID        int64
	Name      string
	Address   string
	Phone     string
	Website   string
	Email     string
	Rating    float64
	Query     string
	ScrapedAt time.Time
}

var (
	emailRegex = regexp.MustCompile(`(?i)\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b`)

	invalidEmailPatterns = []string{
		"example.com",
		"@example",
		".png",
		".jpg",
		".gif",
		"sampleemail",
		"youremail",
		"noreply",
	}

	phonePatterns = []*regexp.Regexp{
		regexp.MustCompile(`\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}`),
		regexp.MustCompile(`\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}`),
	}

	nonDigitRegexp = regexp.MustCompile(`\D`)

	googleMapsResultSelectors = []string{
		`a[href*="/maps/place/"]`,
		`div.Nv2PK a`,
		`a.hfpxzc`,
		`div[role="article"] a`,
	}

	mapsWebsiteSkipKeywords = []string{
		"google",
		"facebook",
		"instagram",
		"youtube",
		"linkedin",
		"twitter",
		"gstatic",
		"googleapis",
		"schema.org",
	}

	socialDomainsToSkip = []string{
		"facebook.com",
		"linkedin.com",
		"instagram.com",
		"youtube.com",
		"twitter.com",
	}

	websiteRegex = regexp.MustCompile(`https?://[a-zA-Z0-9.\-]+\.[A-Za-z]{2,}(?:/[^\s"<>]*)?`)
)

func loadConfig(path string) (*Config, error) {
	cfg := defaultConfig

	data, err := os.ReadFile(path)
	if err != nil {
		log.Printf("[!] Could not read config file %s, using defaults: %v", path, err)
		return &cfg, nil
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		log.Printf("[!] Invalid config file %s, using defaults: %v", path, err)
		return &cfg, nil
	}
	return &cfg, nil
}

func buildQueries(cfg *Config) ([]string, error) {
	search := strings.TrimSpace(cfg.SearchTerm)
	if search == "" {
		fmt.Println("\n[*] What would you like to search for?")
		fmt.Println("Examples: 'Cleaning Service', 'Restaurant', 'Hotel', 'Law Firm', etc.")
		fmt.Print("\n> Search term: ")

		scanner := bufio.NewScanner(os.Stdin)
		if scanner.Scan() {
			search = strings.TrimSpace(scanner.Text())
		}
		if err := scanner.Err(); err != nil {
			return nil, err
		}
		if search == "" {
			return nil, errors.New("no search term entered")
		}
	}

	cfg.SearchTerm = search

	if len(cfg.Locations) == 0 {
		fmt.Println("[!] Warning: No locations found in config.json")
		fmt.Println("[!] Please add a 'locations' array to your config.json file")
		return nil, errors.New("no locations in config.json")
	}

	fmt.Printf("\n[*] Using %d location(s) from config.json:\n", len(cfg.Locations))
	for _, loc := range cfg.Locations {
		fmt.Printf("   - %s\n", loc)
	}

	queries := make([]string, 0, len(cfg.Locations))
	for _, city := range cfg.Locations {
		city = strings.TrimSpace(city)
		if city == "" {
			continue
		}
		queries = append(queries, fmt.Sprintf("%s %s", search, city))
	}
	if len(queries) == 0 {
		return nil, errors.New("no valid locations in config.json")
	}
	return queries, nil
}

func initDB(path string) (*sql.DB, error) {
	db, err := sql.Open("sqlite3", path)
	if err != nil {
		return nil, err
	}

	db.SetMaxOpenConns(1)

	if _, err := db.Exec(`PRAGMA journal_mode = WAL;`); err != nil {
		log.Printf("[!] Failed to set WAL mode: %v", err)
	}
	if _, err := db.Exec(`PRAGMA foreign_keys = ON;`); err != nil {
		log.Printf("[!] Failed to enable foreign keys: %v", err)
	}

	schema := `
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    address TEXT,
    phone TEXT,
    website TEXT,
    email TEXT,
    rating REAL,
    query TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_businesses_email_website ON businesses(email, website);
CREATE INDEX IF NOT EXISTS idx_businesses_website ON businesses(website);
CREATE INDEX IF NOT EXISTS idx_businesses_email ON businesses(email);
`
	if _, err := db.Exec(schema); err != nil {
		db.Close()
		return nil, err
	}

	return db, nil
}

func setupChrome(parent context.Context, headless bool) (context.Context, context.CancelFunc) {
	opts := append(chromedp.DefaultExecAllocatorOptions[:],
		chromedp.Flag("headless", headless),
		chromedp.Flag("disable-gpu", true),
		chromedp.Flag("no-sandbox", true),
		chromedp.Flag("disable-dev-shm-usage", true),
		chromedp.Flag("disable-notifications", true),
		chromedp.Flag("disable-popup-blocking", true),
		chromedp.UserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "+
			"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
	)

	if path := os.Getenv("CHROME_PATH"); path != "" {
		opts = append(opts, chromedp.ExecPath(path))
	}

	allocCtx, allocCancel := chromedp.NewExecAllocator(parent, opts...)
	ctx, cancel := chromedp.NewContext(allocCtx)

	return ctx, func() {
		cancel()
		allocCancel()
	}
}

func acceptCookies(ctx context.Context) {
	selectors := []string{
		`button[aria-label="Accept all"]`,
		`button[aria-label="I agree"]`,
		`button[aria-label="Accept all cookies"]`,
		`button[jsname="b3VHJd"]`,
	}
	texts := []string{
		"Accept all",
		"I agree",
		"Accept cookies",
		"Agree to all",
	}

	for _, sel := range selectors {
		err := chromedp.Run(ctx,
			chromedp.WaitReady("body", chromedp.ByQuery),
			chromedp.Sleep(500*time.Millisecond),
			chromedp.Click(sel, chromedp.ByQuery, chromedp.NodeVisible),
		)
		if err == nil {
			time.Sleep(1500 * time.Millisecond)
			return
		}
	}

	for _, text := range texts {
		xp := fmt.Sprintf(`//button[contains(., "%s")]`, text)
		err := chromedp.Run(ctx,
			chromedp.Click(xp, chromedp.BySearch, chromedp.NodeVisible),
		)
		if err == nil {
			time.Sleep(1500 * time.Millisecond)
			return
		}
	}
}

func collectPlaceURLs(ctx context.Context, cfg *Config, maxResults int) ([]string, error) {
	var resultSelector string

	for _, sel := range googleMapsResultSelectors {
		var count int
		script := fmt.Sprintf(`document.querySelectorAll(%q).length`, sel)
		if err := chromedp.Run(ctx, chromedp.Evaluate(script, &count)); err == nil && count > 0 {
			resultSelector = sel
			log.Printf("   [+] Using selector: %s", sel)
			break
		}
	}

	if resultSelector == "" {
		return nil, errors.New("could not find results panel")
	}

	allURLs := make(map[string]struct{})

	lastCount := 0
	scrollAttempts := 0
	noNewCount := 0

	pause := time.Duration(cfg.ScrollPauseTime * float64(time.Second))
	if pause <= 0 {
		pause = 2 * time.Second
	}
	maxScrolls := cfg.MaxScrollAttempts
	if maxScrolls <= 0 {
		maxScrolls = 20
	}

	for scrollAttempts < maxScrolls {
		var urls []string
		script := fmt.Sprintf(`(function() {
            const els = Array.from(document.querySelectorAll(%q));
            const hrefs = [];
            for (const el of els) {
                const href = el.href || el.getAttribute("href");
                if (href && href.includes("/maps/place/")) {
                    hrefs.push(href);
                }
            }
            return hrefs;
        })()`, resultSelector)

		if err := chromedp.Run(ctx, chromedp.Evaluate(script, &urls)); err != nil {
			log.Printf("   [!] Error collecting result URLs: %v", err)
		} else {
			for _, u := range urls {
				allURLs[u] = struct{}{}
			}
			currentCount := len(allURLs)
			if currentCount > lastCount {
				log.Printf("   [>] Found %d results so far...", currentCount)
				lastCount = currentCount
				noNewCount = 0
			} else {
				noNewCount++
				if noNewCount >= 3 {
					log.Printf("   [+] No more results found after %d scrolls", scrollAttempts)
					break
				}
			}
		}

		var scrolled bool
		scrollScript := `(function() {
            var panel = document.querySelector('div[role="feed"]');
            if (panel) {
                panel.scrollTop = panel.scrollHeight;
                return true;
            } else {
                window.scrollBy(0, 1000);
                return false;
            }
        })()`

		if err := chromedp.Run(ctx, chromedp.Evaluate(scrollScript, &scrolled)); err != nil {
			log.Printf("   [!] Scroll error: %v", err)
		}

		scrollAttempts++
		time.Sleep(pause)
	}

	results := make([]string, 0, len(allURLs))
	for u := range allURLs {
		results = append(results, u)
	}

	if maxResults > 0 && len(results) > maxResults {
		results = results[:maxResults]
	}

	log.Printf("[+] Collected %d unique results", len(results))
	return results, nil
}

func scrapeQuery(ctx context.Context, db *sql.DB, cfg *Config, query string) {
	log.Printf("\n[*] Google Maps search: '%s'\n", query)

	searchURL := "https://www.google.com/maps/search/" + strings.ReplaceAll(query, " ", "+")

	if err := chromedp.Run(ctx,
		chromedp.Navigate(searchURL),
		chromedp.WaitReady("body", chromedp.ByQuery),
	); err != nil {
		log.Printf("[X] Failed to open Google Maps: %v", err)
		return
	}

	acceptCookies(ctx)
	log.Println("[*] Waiting for search results...")
	time.Sleep(4 * time.Second)
	acceptCookies(ctx)

	placeURLs, err := collectPlaceURLs(ctx, cfg, cfg.MaxResultsPerQuery)
	if err != nil {
		log.Printf("[X] %v", err)
		return
	}

	for i, placeURL := range placeURLs {
		log.Printf("\n   Company %d/%d", i+1, len(placeURLs))
		if err := scrapePlacePage(ctx, db, cfg, placeURL, query); err != nil {
			log.Printf("      [X] Error: %v", err)
		}
		randomDelay(3, 7)
	}
}

func scrapePlacePage(ctx context.Context, db *sql.DB, cfg *Config, placeURL, query string) error {
	ctxTimeout, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()

	if err := chromedp.Run(ctxTimeout,
		chromedp.Navigate(placeURL),
		chromedp.WaitReady("body", chromedp.ByQuery),
		chromedp.Sleep(2*time.Second),
	); err != nil {
		return fmt.Errorf("navigate place page: %w", err)
	}

	acceptCookies(ctxTimeout)

	var pageHTML string
	if err := chromedp.Run(ctxTimeout,
		chromedp.OuterHTML("html", &pageHTML, chromedp.ByQuery),
	); err != nil {
		return fmt.Errorf("get page html: %w", err)
	}

	name := extractTextBySelectors(ctxTimeout, []string{
		"h1.DUwDvf",
		"h1.fontHeadlineLarge",
	})
	if name == "" {
		name = "Unknown"
	}

	address := extractTextBySelectors(ctxTimeout, []string{
		`button[data-item-id="address"]`,
		`[data-item-id="address"]`,
		`button[aria-label*="Address"]`,
	})

	phone := extractPhone(pageHTML, cfg.PhoneMinDigits)
	email := extractFirstEmail(pageHTML)

	website := extractWebsiteFromHTML(pageHTML)
	if website == "" {
		if w, ok := getAttribute(ctxTimeout, `a[data-item-id="authority"]`, "href"); ok {
			website = w
		}
	}
	website = cleanWebsiteURL(website)

	ratingStr := extractTextBySelectors(ctxTimeout, []string{
		`span.F7nice`,
		`span[aria-label$="stars"]`,
	})
	rating := parseRating(ratingStr)

	if website != "" && !isSocialDomain(website) && !strings.Contains(strings.ToLower(website), "g.page") {
		wEmail, wPhone, err := scrapeWebsite(ctxTimeout, cfg, website)
		if err != nil {
			log.Printf("      [!] Website error (%s): %v", website, err)
		} else {
			if wEmail != "" {
				email = wEmail
			}
			if wPhone != "" && phone == "" {
				phone = wPhone
			}
		}
	}

	b := &Business{
		Name:      name,
		Address:   address,
		Phone:     phone,
		Website:   website,
		Email:     email,
		Rating:    rating,
		Query:     query,
		ScrapedAt: time.Now().UTC(),
	}

	if err := insertBusiness(db, b); err != nil {
		return fmt.Errorf("insert business: %w", err)
	}

	if isGoldWebsite(website) {
		log.Printf("   GOLD → no website: %s (%s)", b.Name, website)
	} else {
		log.Printf("   [+] Saved: %s | %s | %s", b.Name, b.Email, b.Website)
	}

	return nil
}

func extractTextBySelectors(ctx context.Context, selectors []string) string {
	for _, sel := range selectors {
		var text string
		err := chromedp.Run(ctx,
			chromedp.Text(sel, &text, chromedp.NodeVisible, chromedp.ByQuery),
		)
		if err == nil {
			t := strings.TrimSpace(text)
			if t != "" {
				return t
			}
		}
	}
	return ""
}

func getAttribute(ctx context.Context, selector, attr string) (string, bool) {
	var val string
	var ok bool
	if err := chromedp.Run(ctx,
		chromedp.AttributeValue(selector, attr, &val, &ok, chromedp.ByQuery),
	); err != nil || !ok {
		return "", false
	}
	return strings.TrimSpace(val), true
}

func extractWebsiteFromHTML(html string) string {
	matches := websiteRegex.FindAllString(html, -1)
	for _, m := range matches {
		u := strings.TrimSpace(m)
		lower := strings.ToLower(u)
		skip := false
		for _, bad := range mapsWebsiteSkipKeywords {
			if strings.Contains(lower, bad) {
				skip = true
				break
			}
		}
		if skip {
			continue
		}
		return u
	}
	return ""
}

func cleanWebsiteURL(u string) string {
	u = strings.TrimSpace(u)
	if u == "" {
		return ""
	}

	if strings.Contains(u, "/url?q=") {
		parts := strings.Split(u, "/url?q=")
		if len(parts) > 1 {
			u = parts[1]
			if idx := strings.Index(u, "&"); idx != -1 {
				u = u[:idx]
			}
		}
	}

	if idx := strings.IndexAny(u, "?#"); idx != -1 {
		u = u[:idx]
	}
	return u
}

func parseRating(text string) float64 {
	text = strings.TrimSpace(text)
	if text == "" {
		return 0
	}

	re := regexp.MustCompile(`\d+(?:[.,]\d+)?`)
	num := re.FindString(text)
	if num == "" {
		return 0
	}

	num = strings.ReplaceAll(num, ",", ".")
	v, err := strconv.ParseFloat(num, 64)
	if err != nil {
		return 0
	}
	return v
}

func extractEmails(text string) []string {
	matches := emailRegex.FindAllString(text, -1)
	if len(matches) == 0 {
		return nil
	}

	seen := make(map[string]struct{})
	out := make([]string, 0, len(matches))
	for _, e := range matches {
		email := strings.TrimSpace(e)
		lower := strings.ToLower(email)
		if _, exists := seen[lower]; exists {
			continue
		}
		invalid := false
		for _, inv := range invalidEmailPatterns {
			if strings.Contains(lower, inv) {
				invalid = true
				break
			}
		}
		if invalid {
			continue
		}
		seen[lower] = struct{}{}
		out = append(out, email)
	}
	return out
}

func extractFirstEmail(text string) string {
	emails := extractEmails(text)
	if len(emails) == 0 {
		return ""
	}
	return emails[0]
}

func extractPhone(text string, minDigits int) string {
	for _, re := range phonePatterns {
		matches := re.FindAllString(text, -1)
		for _, m := range matches {
			digits := nonDigitRegexp.ReplaceAllString(m, "")
			if len(digits) < minDigits || len(digits) > 15 {
				continue
			}
			if isInvalidPhone(digits) {
				continue
			}
			return formatPhone(m)
		}
	}
	return ""
}

func isInvalidPhone(digits string) bool {
	if len(digits) == 8 {
		if year, err := strconv.Atoi(digits[:4]); err == nil {
			if year >= 1900 && year <= 2100 {
				return true
			}
		}
	}
	if len(digits) > 15 {
		return true
	}
	allSame := true
	for i := 1; i < len(digits); i++ {
		if digits[i] != digits[0] {
			allSame = false
			break
		}
	}
	return allSame
}

func formatPhone(phone string) string {
	digits := nonDigitRegexp.ReplaceAllString(phone, "")
	if len(digits) == 10 {
		return fmt.Sprintf("(%s) %s-%s", digits[:3], digits[3:6], digits[6:])
	}
	if len(digits) == 11 && digits[0] == '1' {
		return fmt.Sprintf("+1 (%s) %s-%s", digits[1:4], digits[4:7], digits[7:])
	}
	return phone
}

func isSocialDomain(u string) bool {
	lu := strings.ToLower(u)
	for _, d := range socialDomainsToSkip {
		if strings.Contains(lu, d) {
			return true
		}
	}
	return false
}

func isGoldWebsite(website string) bool {
	w := strings.TrimSpace(strings.ToLower(website))
	if w == "" {
		return true
	}
	if strings.Contains(w, "g.page") {
		return true
	}
	return false
}

func scrapeWebsite(parent context.Context, cfg *Config, url string) (string, string, error) {
	ctx, cancel := context.WithTimeout(parent, 30*time.Second)
	defer cancel()

	log.Printf("      [*] Scanning website: %s", url)

	if err := chromedp.Run(ctx,
		chromedp.Navigate(url),
		chromedp.WaitReady("body", chromedp.ByQuery),
		chromedp.Sleep(2*time.Second),
	); err != nil {
		return "", "", err
	}

	var html string
	if err := chromedp.Run(ctx,
		chromedp.OuterHTML("html", &html, chromedp.ByQuery),
	); err != nil {
		return "", "", err
	}

	email := extractFirstEmail(html)
	phone := extractPhone(html, cfg.PhoneMinDigits)

	if email == "" {
		if contactURL := findContactLink(ctx); contactURL != "" {
			log.Printf("      [*] Following contact page: %s", contactURL)
			if err := chromedp.Run(ctx,
				chromedp.Navigate(contactURL),
				chromedp.WaitReady("body", chromedp.ByQuery),
				chromedp.Sleep(2*time.Second),
			); err == nil {
				if err := chromedp.Run(ctx,
					chromedp.OuterHTML("html", &html, chromedp.ByQuery),
				); err == nil {
					email = extractFirstEmail(html)
					if phone == "" {
						phone = extractPhone(html, cfg.PhoneMinDigits)
					}
				}
			}
		}
	}

	return email, phone, nil
}

func findContactLink(ctx context.Context) string {
	js := `(function() {
        const keywords = [
            "Contact","contact","CONTACT",
            "Kontakt","kontakt",
            "Contacto","contacto",
            "Contatto","contatto",
            "Contactez","contactez",
            "Impressum","impressum",
            "About","about"
        ];
        const anchors = Array.from(document.querySelectorAll('a'));
        for (const a of anchors) {
            const text = (a.innerText || a.textContent || '').trim();
            const href = a.href || a.getAttribute('href') || '';
            if (!href) continue;
            for (const kw of keywords) {
                if (text.includes(kw)) {
                    return href;
                }
            }
        }
        return '';
    })()`
	var href string
	if err := chromedp.Run(ctx, chromedp.Evaluate(js, &href)); err != nil {
		return ""
	}
	href = strings.TrimSpace(href)
	if href == "" {
		return ""
	}
	if strings.HasPrefix(href, "//") {
		href = "https:" + href
	}
	return href
}

func insertBusiness(db *sql.DB, b *Business) error {
	const stmt = `INSERT OR IGNORE INTO businesses
        (name, address, phone, website, email, rating, query, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);`

	_, err := db.Exec(stmt,
		b.Name,
		b.Address,
		b.Phone,
		b.Website,
		b.Email,
		b.Rating,
		b.Query,
		b.ScrapedAt.Format(time.RFC3339),
	)
	return err
}

func randomDelay(minSec, maxSec int) {
	if maxSec <= minSec {
		time.Sleep(time.Duration(minSec) * time.Second)
		return
	}
	delta := maxSec - minSec + 1
	n := rand.Intn(delta)
	time.Sleep(time.Duration(minSec+n) * time.Second)
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)

	configPath := flag.String("config", "config.json", "Path to config.json")
	flag.Parse()

	rand.Seed(time.Now().UnixNano())

	fmt.Println(strings.Repeat("=", 70))
	fmt.Println("   EMAIL SCRAPER PROWEBLINE (Go)")
	fmt.Println("   Google Maps Scraping with Browser Automation")
	fmt.Println(strings.Repeat("=", 70))

	cfg, err := loadConfig(*configPath)
	if err != nil {
		log.Fatalf("[X] Failed to load config: %v", err)
	}

	queries, err := buildQueries(cfg)
	if err != nil {
		log.Fatalf("[X] %v", err)
	}

	fmt.Printf("\n[*] Configuration:\n")
	fmt.Printf("   - Headless mode: %v\n", cfg.Headless)
	fmt.Printf("   - Multi-threading (unused in Go): %v\n", cfg.UseThreading)
	if cfg.UseThreading {
		fmt.Printf("   - Thread workers: %d\n", cfg.MaxThreadWorkers)
	}
	fmt.Printf("   - Scroll pause: %.1fs\n", cfg.ScrollPauseTime)
	fmt.Printf("   - Max scroll attempts: %d\n", cfg.MaxScrollAttempts)

	if cfg.MaxResultsPerQuery <= 0 {
		fmt.Println("[*] No limit set - will scrape all available results")
	} else {
		fmt.Printf("[*] Max results per query: %d\n", cfg.MaxResultsPerQuery)
	}

	db, err := initDB(dbFileName)
	if err != nil {
		log.Fatalf("[X] Failed to initialize database: %v", err)
	}
	defer db.Close()

	rootCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	ctx, cancelChrome := setupChrome(rootCtx, cfg.Headless)
	defer cancelChrome()

	fmt.Printf("\n[*] Starting search for %d querie(s)...\n", len(queries))
	fmt.Println("[!] This may take 10-30 minutes depending on results...\n")

	for i, q := range queries {
		if rootCtx.Err() != nil {
			log.Println("[!] Received shutdown signal, stopping.")
			break
		}

		fmt.Println(strings.Repeat("=", 60))
		fmt.Printf("Search Query %d/%d: %s\n", i+1, len(queries), q)
		fmt.Println(strings.Repeat("=", 60))

		scrapeQuery(ctx, db, cfg, q)

		if i < len(queries)-1 {
			fmt.Println("\n[*] Waiting before next query...")
			randomDelay(3, 7)
		}
	}

	fmt.Println("\nDone! Open leads_greece_2025.sqlite with DB Browser for SQLite or DuckDB")
}


