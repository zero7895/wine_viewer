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

## 常用指令

- 更新資料（一般使用）：`python scrape_littlewine.py`
- 強制全部重抓：`python scrape_littlewine.py --refresh`
- 只重生 HTML（不重抓資料、不下載圖片）：`python scrape_littlewine.py --render-only`
- 顯示瀏覽器（除錯）：`python scrape_littlewine.py --headed`
- 指定賣場：`python scrape_littlewine.py --markets "全聯,家樂福"`
- 每賣場只抓前 N 筆：`python scrape_littlewine.py --limit 3`

## 參數

- `--headed`
- `--limit N`
- `--markets "賣場1,賣場2"`
- `--refresh`
- `--render-only`
- `--input-json PATH`（預設：`docs/data/littlewine_red_pxmart_links.json`）

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
