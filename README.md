# Littlewine Scraper

此專案會使用 Playwright 自動操作 `https://littlewine.com.tw/` 的「進階搜尋」，套用以下條件：

- 酒種：紅酒
- 賣場：大全聯、全聯（各跑一次）

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

若要看到瀏覽器操作畫面（除錯用）：

```bash
python scrape_littlewine.py --headed
```

## 輸出格式

- HTML：可直接開啟瀏覽所有酒款連結，且上方有賣場標籤可篩選（全部 / 大全聯 / 全聯）
- CSV：`market,title,url,region,country,grape,abv,vintage,winery,sweetness,acidity,body,rating,reference_price,image_url,image_path`
- JSON：陣列格式，每筆含上述欄位

程式會逐一進入每個酒款頁，嘗試擷取：`產區`、`國家`、`葡萄品種`、`酒精濃度`、`年份`、`酒莊(廠)`、`甜度`、`酸度`、`飽滿度`、`星等`、`參考價`，並顯示在 HTML 表格中。
同時也會抓取酒款圖片（優先 `.body_UI_img img`），下載到 `images/`，並在 HTML 表格中以縮圖呈現。

## 備註

網站若改版（按鈕文字或版面結構改變）可能導致定位失敗，請調整 `scrape_littlewine.py` 裡的 selector 候選清單。
