"""
資安事件內文抽取與分類引擎
"""
import re
import datetime

def normalize_date(year, month, day):
    try:
        y = int(year) if year else 2026
        m = int(month)
        d = int(day)
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None

def extract_incident_details(article):
    """
    從新聞標題與內文自動抽取：
    - 股票代號與公司名稱
    - 侵入日、內部發現日、公開揭露日
    - 攻擊類型與衝擊等級分類
    """
    title = article.get("title", "")
    content = article.get("content", "")
    published_at = article.get("published_at", "")
    full_text = f"{title}\n{content}"
    
    # 預設基準年份（從發布日期獲取）
    pub_year = 2026
    if published_at:
        try:
            pub_year = int(published_at.split("-")[0])
        except Exception:
            pass

    # 1. 抽取股票代號與公司名稱
    # 常見模式：神腦國際（2450）、鈊象（3293）、柏文（8462）
    stock_match = re.search(r'([\u4e00-\u9fa5A-Za-z0-9\-]+)[（\(](\d{4})[）\)]', full_text)
    stock_code = None
    company_name = None
    if stock_match:
        company_name = stock_match.group(1).replace("上市公司", "").replace("上櫃公司", "").strip()
        stock_code = stock_match.group(2)
    else:
        # 標題若有股票代號
        simple_code = re.search(r'[（\(](\d{4})[）\)]', title)
        if simple_code:
            stock_code = simple_code.group(1)

    # 2. 抽取三大關鍵日期
    disclosure_date = None  # 公開揭露日（重訊日）
    discovery_date = None   # 內部發現日
    intrusion_date = None   # 侵入日/攻擊發生日

    # A. 公開揭露日 (Disclosure Date)
    # 常見模式：「9月29日，在股市公開資訊觀測站發布重大訊息」
    disc_pattern = re.search(
        r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日號][^。\n]{0,35}?(?:重大訊息|公開資訊觀測站|發布資安重訊|公告|說明)',
        full_text
    )
    if disc_pattern:
        y, m, d = disc_pattern.groups()
        disclosure_date = normalize_date(y or pub_year, m, d)
    else:
        disclosure_date = published_at

    # B. 內部發現日 (Discovery Date)
    # 常見模式：「10月8日偵測到內部系統遭到異常存取」、「兩天前（10月14日）發現遭受自動化攻擊」
    disc_team_pattern = re.search(
        r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日號][^。\n]{0,30}?(?:偵測到|察覺|發現|獲報|接獲|通知|察覺有異)',
        full_text
    )
    if disc_team_pattern:
        y, m, d = disc_team_pattern.groups()
        discovery_date = normalize_date(y or pub_year, m, d)
    else:
        # 檢查是否有「X天前發現」
        rel_pattern = re.search(r'(\d+)天前[^。\n]{0,10}?(?:偵測到|察覺|發現)', full_text)
        if rel_pattern and disclosure_date:
            days_ago = int(rel_pattern.group(1))
            try:
                base_dt = datetime.datetime.strptime(disclosure_date, "%Y-%m-%d")
                discovery_date = (base_dt - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")
            except Exception:
                pass
    
    if not discovery_date:
        discovery_date = disclosure_date

    # C. 侵入日/攻擊發生日 (Intrusion / Breach Date)
    # 常見模式：「9月7日旗下子公司格帝控股部分伺服器遭勒索病毒攻擊」
    intru_pattern = re.search(
        r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日號][^。\n]{0,30}?(?:遭受|遭到|遭|被|入侵|攻擊|植入|中毒|加密|讀取)',
        full_text
    )
    if intru_pattern:
        y, m, d = intru_pattern.groups()
        intrusion_date = normalize_date(y or pub_year, m, d)
    else:
        intrusion_date = discovery_date

    # 3. 攻擊類型分類 (Attack Category Classification)
    attack_categories = []
    if re.search(r'勒索|加密鎖定|黑客加密|Ransomware', full_text, re.IGNORECASE):
        attack_categories.append("勒索軟體 (Ransomware)")
    if re.search(r'自動化攻擊|撞庫|嘗試登入|帳密|暴力破解|Credential Stuffing', full_text, re.IGNORECASE):
        attack_categories.append("自動化帳密攻擊 (Credential Stuffing)")
    if re.search(r'個資|外洩|外流|履歷|訂單資訊|資料遭竊|Data Breach', full_text, re.IGNORECASE):
        attack_categories.append("資料外洩 (Data Breach)")
    if re.search(r'異常讀取|未經授權存取|侵入|入侵|滲透|未授權', full_text, re.IGNORECASE):
        attack_categories.append("未授權存取/入侵 (Unauthorized Access)")
    if re.search(r'委外廠商|第三方平臺|供應鏈', full_text, re.IGNORECASE):
        attack_categories.append("第三方/供應鏈事故 (Third-Party Incident)")
    if re.search(r'DDoS|阻斷服務|流量攻擊', full_text, re.IGNORECASE):
        attack_categories.append("阻斷服務攻擊 (DDoS)")
        
    if not attack_categories:
        attack_categories.append("一般網路安全事故 (General Cyber Incident)")

    # 4. 影響範圍與等級分類 (Impact Scope Classification)
    impact_types = []
    if re.search(r'ERP|產線|無法運作|系統停擺|工廠停工|中斷', full_text):
        impact_types.append("核心系統/ERP停擺")
    if re.search(r'個資外流|詐騙|消費者|會員個資|履歷資料', full_text):
        impact_types.append("顧客個資外洩風險")
    if re.search(r'對外服務|官網|網站|App系統異常', full_text):
        impact_types.append("外部服務/APP暫時受阻")
    if re.search(r'無重大影響|不致有重大影響|未受波及|已隔離', full_text):
        impact_types.append("初步評估無重大財務影響")
    
    # 5. 抽取官方影響聲明句子
    statement_match = re.search(r'[^。\n]*?(?:初步評估|預估|評估)[^。\n]*?(?:影響|損失)[^。\n]*?。', full_text)
    impact_statement = statement_match.group(0).strip() if statement_match else "未特別提及或無重大影響"

    return {
        "stock_code": stock_code,
        "company_name": company_name,
        "dates": {
            "intrusion_date": intrusion_date,       # 侵入日
            "discovery_date": discovery_date,       # 內部發現日
            "disclosure_date": disclosure_date,     # 公開揭露日 (t=0)
            "reporting_date": published_at          # iThome報導發布日
        },
        "attack_categories": attack_categories,
        "impact_types": impact_types,
        "impact_statement": impact_statement
    }
