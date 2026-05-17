# Littlewine Scraper

此專案會使用 Playwright 自動操作 `https://littlewine.com.tw/` 的「進階搜尋」，套用以下條件：

- 酒種：紅酒
- 賣場：大全聯、全聯、好市多、家樂福、美廉社、大潤發、愛買（預設全抓）

並輸出三種結果檔案：

- `red_wine.html`
- `littlewine_red_pxmart_links.csv`
- `littlewine_red_pxmart_links.json`

## 安裝

### 方式 A：使用 conda（推薦）

```bash
conda create -n littlewine-scraper python=3.11 -y
conda activate littlewine-scraper
pip install -r requirements.txt
python -m playwright install chromium
```

### 方式 B：使用 venv

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

預設行為：

- 未給 `--markets`：會抓全部賣場（大全聯、全聯、好市多、家樂福、美廉社、大潤發、愛買）
- 未給 `--refresh`：會重用已存在於 `littlewine_red_pxmart_links.json` 的解析結果，不重複 parse

## 常用情境（先看這裡）

- 想更新資料（一般使用）：`python scrape_littlewine.py`
- 想強制全部重抓：`python scrape_littlewine.py --refresh`
- 只改頁面排版，不想重抓資料：`python scrape_littlewine.py --render-only`

## 參數總覽

- `--headed`：顯示瀏覽器畫面（除錯用）
- `--limit N`：每個賣場只取前 `N` 筆連結（例如 `--limit 3`）
- `--markets "賣場1,賣場2"`：只抓指定賣場（逗號分隔）
- `--refresh`：忽略 JSON 快取，強制重抓所有詳細頁
- `--render-only`：只用既有 JSON 重新產生 HTML（不抓資料、不下載圖片）
- `--input-json PATH`：搭配 `--render-only` 指定 JSON 檔案路徑

若要看到瀏覽器操作畫面（除錯用）：

```bash
python scrape_littlewine.py --headed
```

只抓每個賣場前 3 筆：

```bash
python scrape_littlewine.py --limit 3
```

只抓指定賣場（逗號分隔）：

```bash
python scrape_littlewine.py --markets "全聯,家樂福"
```

指定賣場 + 每賣場前 3 筆：

```bash
python scrape_littlewine.py --markets "全聯,家樂福" --limit 3
```

強制重抓詳細頁（忽略快取）：

```bash
python scrape_littlewine.py --refresh
```

可搭配使用：

```bash
python scrape_littlewine.py --markets "全聯,家樂福" --refresh --limit 3
```

只改網頁排版時（不重抓資料）建議使用：

```bash
python scrape_littlewine.py --render-only
```

若 JSON 在其他路徑：

```bash
python scrape_littlewine.py --render-only --input-json /path/to/your.json
```

## 快取機制

- 連結列表每次都會重新抓（用來發現新酒款）
- 詳細頁會用 `littlewine_red_pxmart_links.json` 做快取比對（key 為 `market + url`）
- 抓過且存在快取的項目會直接重用，不重新進詳細頁 parse
- 使用 `--refresh` 時會關閉上述快取重用，全部重抓

## 輸出格式

- HTML：可直接開啟瀏覽所有酒款連結，支援下列互動
  - 賣場篩選（按鈕）
  - 國家篩選（下拉選單）
  - 排序切換（星等高到低 / 參考價高到低）
  - 預設排序為星等高到低
- CSV：`market,title,url,region,country,grape,abv,vintage,winery,sweetness,acidity,body,rating,reference_price,image_url,image_path`
- JSON：陣列格式，每筆含上述欄位

程式會逐一進入每個酒款頁，嘗試擷取：`產區`、`國家`、`葡萄品種`、`酒精濃度`、`年份`、`酒莊(廠)`、`甜度`、`酸度`、`飽滿度`、`星等`、`參考價`，並顯示在 HTML 表格中。
同時也會抓取酒款圖片（優先 `.body_UI_img img`），下載到 `images/`，並在 HTML 表格中以縮圖呈現。

## 備註

網站若改版（按鈕文字或版面結構改變）可能導致定位失敗，請調整 `scrape_littlewine.py` 裡的 selector 候選清單。
