# scripts/

> 開發用腳本。**不會被 MkDocs 收錄**（不在 `docs/` 內）。

## fetch_neijing.py — 抓取《黃帝內經》原文

從 zh.wikisource.org 與 ctext.org 兩處輪替抓取 33 篇高頻引用篇之原文，自動填入 `docs/原文/` 之對應檔。

### 安裝套件

```powershell
pip install requests beautifulsoup4
```

### 執行

```powershell
# 抓全部 33 篇
python scripts/fetch_neijing.py

# 只抓單篇（建議先測一篇看格式對不對）
python scripts/fetch_neijing.py --chapter 至真要大論

# 只抓素問
python scripts/fetch_neijing.py --book 素問

# Dry-run（不寫檔，只看會抓到什麼）
python scripts/fetch_neijing.py --dry-run

# 強制只用某一來源
python scripts/fetch_neijing.py --source wikisource
python scripts/fetch_neijing.py --source ctext

# 調整篇間延遲（避免太快被 ban）
python scripts/fetch_neijing.py --delay 5
```

### 來源說明

| 來源 | 內容 | 優點 | 限制 |
|---|---|---|---|
| **zh.wikisource.org** | 王冰注本（部分含註） | 較完整、含註 | 段落分割可能不規整 |
| **ctext.org** | 純原文 | 段落清楚 | 無王冰注 |

預設策略 `--source auto`：先試 wikisource、失敗則退到 ctext。

### 注意事項

1. **腳本會覆寫**現有的 `.md` 檔。建議先 `git commit` 或備份。
2. **需手動校對**：尤其是 wikisource 抓到的內容，標點符號與分段可能需要調整。
3. **王冰注**抓到的部分需要進一步整理——wikisource 的格式不一定一致。
4. 抓取速度受網路與目標站台 rate-limit 影響，建議 `--delay 2` 以上。

### 抓取後的工作流程

```
1. python scripts/fetch_neijing.py --chapter 至真要大論
   → 看 docs/原文/素問/至真要大論.md 結果

2. 若格式 OK → 全部抓：
   python scripts/fetch_neijing.py

3. 校對：手動修正標點、分段、王冰注配對

4. git commit, push
```
