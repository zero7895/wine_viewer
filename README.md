# Littlewine Scraper (GitHub Pages Ready)

這個專案會用 Playwright 抓取 `https://littlewine.com.tw/` 紅酒資料，並直接輸出成可部署到 GitHub Pages 的格式。

預設抓取賣場：大全聯、全聯、好市多、家樂福、美廉社、大潤發、愛買。

## 輸出位置（直接給 GitHub Pages 用）

- `docs/index.html`（網站首頁）
- `docs/images/`（酒款縮圖）
- `docs/data/littlewine_red_pxmart_links.json`
- `docs/data/littlewine_red_pxmart_links.csv`

執行後不會再額外產生根目錄 `red_wine.html` 或根目錄 `images/`。

## 安裝

### 方式 A：conda（推薦）

```bash
conda create -n littlewine-scraper python=3.11 -y
conda activate littlewine-scraper
pip install -r requirements.txt
python -m playwright install chromium
```

### 方式 B：venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## 執行

```bash
python scrape_littlewine.py
```

## 三種主要模式

### 1) 只改 HTML UI（不重抓資料）

```bash
python scrape_littlewine.py --render-only
```

### 2) 抓 littlewine 資料（每賣場 N 筆）

```bash
python scrape_littlewine.py --limit 3
```

- `--limit N` 會只抓 littlewine（不查 Vivino）
- 可搭配 `--markets "全聯,家樂福"`

### 3) 用既有資料補 Vivino 分數（只補缺少的）

```bash
python scrape_littlewine.py --vivino-only
```

- 會用既有 JSON（預設 `docs/data/littlewine_red_pxmart_links.json`）
- 只查沒有快取過的項目，查過會存到 `docs/data/vivino_cache.json`
- 可先小量測試：`python scrape_littlewine.py --vivino-only --vivino-limit-per-market 3`
- 強制重查 Vivino：`python scrape_littlewine.py --vivino-only --refresh-vivino`

## 日常更新建議流程（之後補新資料用）

### A. 有新酒款資料要更新（完整更新）

```bash
python scrape_littlewine.py
```

- 會抓 littlewine 新資料
- 會補 Vivino 分數（已有快取的會重用）
- 會更新 `docs/index.html`、`docs/data/*.json`、`docs/data/*.csv`

### B. 只調整頁面 UI（不重抓資料）

```bash
python scrape_littlewine.py --render-only
```

### C. 先小量驗證再補 Vivino

```bash
# 每個賣場先查 3 筆
python scrape_littlewine.py --vivino-only --vivino-limit-per-market 3 --refresh-vivino

# 確認沒問題後，對既有資料補齊 Vivino（只補缺少的）
python scrape_littlewine.py --vivino-only
```

### D. 要快速抓樣本資料（不查 Vivino）

```bash
python scrape_littlewine.py --limit 3
```

## 常用指令

- 全流程（抓 littlewine + 查 Vivino）：`python scrape_littlewine.py`
- 強制重抓 littlewine：`python scrape_littlewine.py --refresh`
- 只重生 HTML：`python scrape_littlewine.py --render-only`
- 只查 Vivino：`python scrape_littlewine.py --vivino-only`
- 只查 Vivino（每賣場前 3 筆）：`python scrape_littlewine.py --vivino-only --vivino-limit-per-market 3`
- 顯示瀏覽器（除錯）：`python scrape_littlewine.py --headed`

## 參數

- `--headed`
- `--limit N`
- `--markets "賣場1,賣場2"`
- `--refresh`
- `--render-only`
- `--input-json PATH`（預設：`docs/data/littlewine_red_pxmart_links.json`）
- `--vivino-only`
- `--vivino-limit-per-market N`
- `--refresh-vivino`

## GitHub Pages 部署

1. 把專案 push 到 GitHub
2. 到 repo 的 `Settings` -> `Pages`
3. Source 選 `Deploy from a branch`
4. Branch 選 `main`，Folder 選 `/docs`
5. 儲存後等待 1-5 分鐘

網站網址通常是：

- `https://<你的帳號>.github.io/<repo名稱>/`

這個 repo（`https://github.com/zero7895/wine_viewer`）對應的網址是：

- `https://zero7895.github.io/wine_viewer/`

## 首次上線（最短流程）

```bash
python scrape_littlewine.py
git add docs README.md README.html scrape_littlewine.py
git commit -m "prepare GitHub Pages output"
git push
```

然後到 GitHub 設定 `Settings -> Pages`，選 `main` + `/docs`。

## 更新網站流程

```bash
python scrape_littlewine.py
git add docs
git commit -m "update wine data"
git push
```

Push 後 GitHub Pages 會自動更新。

## 每次更新後建議

```bash
git add docs README.md README.html scrape_littlewine.py
git commit -m "update wine data and page"
git push
```
