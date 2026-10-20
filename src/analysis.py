"""
資安事件與股價衝擊 — 統計分析模組 (Statistical Analysis Module)

實作事件研究法 (Event Study) 的完整統計檢定流程：
  RQ1: 整體 CAAR 顯著性 t 檢定
  RQ2: 攻擊類型分組比較 (Mann-Whitney U / Kruskal-Wallis)
  RQ3: 橫斷面 OLS 迴歸（企業特徵對衝擊的調節效果）
  RQ4: 事前資訊外洩檢驗 CAR[-3, -1]
"""
import sys
import os
import re
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from scipy import stats
import statsmodels.api as sm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# ── 字型設定：自動尋找系統中文字型 ────────────────────────
def _setup_chinese_font():
    """嘗試設定中文字型，若找不到則使用 sans-serif fallback"""
    candidates = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei",
                  "Noto Sans CJK TC", "PingFang TC", "Arial Unicode MS"]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    return None

FONT_NAME = _setup_chinese_font()

sys.stdout.reconfigure(encoding="utf-8")

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════
#  Phase 1: 資料載入與清洗
# ══════════════════════════════════════════════════════════════

def load_and_clean(csv_path=None):
    """載入 CSV 並進行變數前處理"""
    if csv_path is None:
        csv_path = os.path.join(DATA_DIR, "cyber_incidents_summary.csv")
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # ── 1. 清理公司名稱前綴 ──
    prefix_pattern = re.compile(r"^(?:本週|上週|9月\d+日晚間|上櫃)")
    df["公司名稱_clean"] = df["公司名稱"].apply(
        lambda x: prefix_pattern.sub("", str(x)).strip() if pd.notna(x) else x
    )

    # ── 2. 百分比字串轉浮點數 ──
    pct_cols = [
        "次日報酬率(Raw)", "3日累計報酬率(Raw)",
        "次日異常報酬率(AR)", "3日累計異常報酬率(CAR)",
        "事前外洩檢驗(CAR[-3,-1])",
    ]
    for col in pct_cols:
        if col in df.columns:
            df[col + "_num"] = (
                df[col]
                .astype(str)
                .str.replace("%", "", regex=False)
                .replace({"N/A": np.nan, "nan": np.nan, "": np.nan})
                .astype(float)
            )

    # ── 3. 成交量放大倍數轉浮點數 ──
    if "成交量放大倍數" in df.columns:
        df["Volume_Shock"] = (
            df["成交量放大倍數"]
            .astype(str)
            .str.replace("x", "", regex=False)
            .replace({"N/A": np.nan, "nan": np.nan, "": np.nan})
            .astype(float)
        )

    # ── 4. 財務指標轉浮點數 ──
    for col in ["本益比", "殖利率", "淨值比"]:
        if col in df.columns:
            df[col + "_num"] = pd.to_numeric(
                df[col].replace({"N/A": np.nan}), errors="coerce"
            )

    # ── 5. 建立虛擬變數 ──
    attack_col = "攻擊類型"
    impact_col = "影響範圍"

    df["D_Ransomware"] = df[attack_col].str.contains("勒索", na=False).astype(int)
    df["D_DataBreach"] = df[attack_col].str.contains("資料外洩|Data Breach", na=False).astype(int)
    df["D_CredentialStuffing"] = df[attack_col].str.contains("帳密|Credential", na=False).astype(int)
    df["D_Unauthorized"] = df[attack_col].str.contains("未授權|Unauthorized", na=False).astype(int)
    df["D_SupplyChain"] = df[attack_col].str.contains("供應鏈|第三方|Third-Party", na=False).astype(int)

    if impact_col in df.columns:
        df["D_ERP_Down"] = df[impact_col].str.contains("ERP|停擺|中斷", na=False).astype(int)
        df["D_CustomerData"] = df[impact_col].str.contains("顧客個資|個資外洩", na=False).astype(int)

    df["D_TWSE"] = (df["市場別"].str.contains("TWSE", na=False)).astype(int)

    # ── 6. 揭露延遲天數 ──
    if "侵入發生日" in df.columns and "公開揭露日" in df.columns:
        try:
            df["侵入日_dt"] = pd.to_datetime(df["侵入發生日"], errors="coerce")
            df["揭露日_dt"] = pd.to_datetime(df["公開揭露日"], errors="coerce")
            df["Disclosure_Lag"] = (df["揭露日_dt"] - df["侵入日_dt"]).dt.days
        except Exception:
            df["Disclosure_Lag"] = 0

    # ── 7. 重複受駭企業標記 ──
    repeat_codes = df["股票代碼"].value_counts()
    repeat_codes = repeat_codes[repeat_codes > 1].index.tolist()
    df["D_Repeat"] = df["股票代碼"].isin(repeat_codes).astype(int)

    # ── 便利別名 ──
    df["AR_1d"] = df.get("次日異常報酬率(AR)_num")
    df["CAR_3d"] = df.get("3日累計異常報酬率(CAR)_num")
    df["CAR_pre"] = df.get("事前外洩檢驗(CAR[-3,-1])_num")

    return df


# ══════════════════════════════════════════════════════════════
#  Phase 2: 描述性統計
# ══════════════════════════════════════════════════════════════

def descriptive_statistics(df):
    """產出描述性統計表"""
    print("\n" + "=" * 70)
    print("  📊 描述性統計 (Descriptive Statistics)")
    print("=" * 70)

    desc_cols = ["AR_1d", "CAR_3d", "CAR_pre", "Volume_Shock",
                 "本益比_num", "殖利率_num", "淨值比_num", "Disclosure_Lag"]
    available = [c for c in desc_cols if c in df.columns]
    desc = df[available].describe().T
    desc["median"] = df[available].median()
    desc = desc[["count", "mean", "std", "min", "25%", "median", "75%", "max"]]

    col_labels = {
        "AR_1d": "次日異常報酬率 AR(%)",
        "CAR_3d": "3日累積異常報酬率 CAR(%)",
        "CAR_pre": "事前外洩 CAR[-3,-1](%)",
        "Volume_Shock": "成交量放大倍數",
        "本益比_num": "本益比 (PE)",
        "殖利率_num": "殖利率 (%)",
        "淨值比_num": "淨值比 (PB)",
        "Disclosure_Lag": "揭露延遲天數",
    }
    desc.index = [col_labels.get(c, c) for c in desc.index]
    print(desc.round(3).to_string())

    # 攻擊類型分布
    print("\n【攻擊類型虛擬變數分布】")
    dummy_cols = [c for c in df.columns if c.startswith("D_")]
    for col in dummy_cols:
        cnt = df[col].sum()
        print(f"  {col}: {int(cnt)} / {len(df)} ({cnt/len(df)*100:.1f}%)")

    return desc


# ══════════════════════════════════════════════════════════════
#  Phase 3: RQ1 — 整體 CAAR 檢定
# ══════════════════════════════════════════════════════════════

def test_rq1(df):
    """RQ1: 資安重訊揭露後，股價 CAR 是否顯著為負？"""
    print("\n" + "=" * 70)
    print("  🔬 RQ1: 整體衝擊檢定 — CAAR 是否顯著異於 0")
    print("=" * 70)

    results = {}
    for label, col in [("AR[+1]", "AR_1d"), ("CAR[0,+3]", "CAR_3d")]:
        data = df[col].dropna()
        n = len(data)
        mean = data.mean()
        std = data.std()
        se = std / np.sqrt(n)

        # t 檢定 (One-sample, two-tailed)
        t_stat, p_two = stats.ttest_1samp(data, 0)
        # 單尾 p 值 (H₁: μ < 0)
        p_one = p_two / 2 if t_stat < 0 else 1 - p_two / 2

        # Wilcoxon 符號等級檢定 (非參數)
        try:
            w_stat, w_p = stats.wilcoxon(data, alternative="two-sided")
        except Exception:
            w_stat, w_p = np.nan, np.nan

        sig_marker = ""
        if p_two < 0.01:
            sig_marker = "***"
        elif p_two < 0.05:
            sig_marker = "**"
        elif p_two < 0.10:
            sig_marker = "*"

        print(f"\n  {label}:")
        print(f"    N = {n}, CAAR = {mean:.3f}%, SE = {se:.3f}%")
        print(f"    t 統計量 = {t_stat:.4f}, p 值 (雙尾) = {p_two:.4f} {sig_marker}")
        print(f"    p 值 (單尾, H₁: μ<0)    = {p_one:.4f}")
        print(f"    Wilcoxon W = {w_stat:.1f}, p = {w_p:.4f}" if not np.isnan(w_stat) else "    Wilcoxon: 樣本不足")
        print(f"    中位數 = {data.median():.3f}%, 正值比例 = {(data > 0).mean()*100:.1f}%")

        results[label] = {
            "N": n, "CAAR": mean, "SE": se,
            "t": t_stat, "p_two": p_two, "p_one": p_one,
            "wilcoxon_w": w_stat, "wilcoxon_p": w_p, "sig": sig_marker
        }

    return results


# ══════════════════════════════════════════════════════════════
#  Phase 4: RQ2 — 攻擊類型分組比較
# ══════════════════════════════════════════════════════════════

def test_rq2(df):
    """RQ2: 不同攻擊類型的市場衝擊是否有差異？"""
    print("\n" + "=" * 70)
    print("  🔬 RQ2: 攻擊類型分組比較")
    print("=" * 70)

    results = {}
    dep_var = "CAR_3d"
    dep = df[dep_var].dropna()

    # 分組統計
    groups = {
        "勒索軟體": "D_Ransomware",
        "帳密撞庫": "D_CredentialStuffing",
        "資料外洩": "D_DataBreach",
        "未授權存取": "D_Unauthorized",
        "供應鏈事故": "D_SupplyChain",
    }

    print(f"\n  依變數: {dep_var}")
    print(f"  {'攻擊類型':<12} {'N':>4} {'平均CAR':>10} {'中位數':>10} {'標準差':>10}")
    print("  " + "-" * 50)

    for label, col in groups.items():
        if col not in df.columns:
            continue
        mask = df[col] == 1
        sub = df.loc[mask, dep_var].dropna()
        if len(sub) == 0:
            continue
        print(f"  {label:<12} {len(sub):>4} {sub.mean():>10.3f}% {sub.median():>10.3f}% {sub.std():>10.3f}%")

    # Mann-Whitney U 檢定: 勒索軟體 vs. 非勒索軟體
    if "D_Ransomware" in df.columns:
        grp_ransom = df.loc[df["D_Ransomware"] == 1, dep_var].dropna()
        grp_other = df.loc[df["D_Ransomware"] == 0, dep_var].dropna()
        if len(grp_ransom) >= 2 and len(grp_other) >= 2:
            u_stat, u_p = stats.mannwhitneyu(grp_ransom, grp_other, alternative="two-sided")
            print(f"\n  【Mann-Whitney U 檢定: 勒索軟體 vs. 其他】")
            print(f"    勒索軟體 (N={len(grp_ransom)}): 平均 = {grp_ransom.mean():.3f}%, 中位數 = {grp_ransom.median():.3f}%")
            print(f"    其他 (N={len(grp_other)}):      平均 = {grp_other.mean():.3f}%, 中位數 = {grp_other.median():.3f}%")
            print(f"    U = {u_stat:.1f}, p = {u_p:.4f}")
            results["ransomware_vs_other"] = {"U": u_stat, "p": u_p}

    # ERP 停擺 vs. 否
    if "D_ERP_Down" in df.columns:
        grp_erp = df.loc[df["D_ERP_Down"] == 1, dep_var].dropna()
        grp_no_erp = df.loc[df["D_ERP_Down"] == 0, dep_var].dropna()
        if len(grp_erp) >= 2 and len(grp_no_erp) >= 2:
            u_stat, u_p = stats.mannwhitneyu(grp_erp, grp_no_erp, alternative="two-sided")
            print(f"\n  【Mann-Whitney U 檢定: ERP 停擺 vs. 未停擺】")
            print(f"    ERP停擺 (N={len(grp_erp)}):  平均 = {grp_erp.mean():.3f}%, 中位數 = {grp_erp.median():.3f}%")
            print(f"    未停擺 (N={len(grp_no_erp)}): 平均 = {grp_no_erp.mean():.3f}%, 中位數 = {grp_no_erp.median():.3f}%")
            print(f"    U = {u_stat:.1f}, p = {u_p:.4f}")
            results["erp_vs_no_erp"] = {"U": u_stat, "p": u_p}

    # 顧客個資外洩 vs. 否
    if "D_CustomerData" in df.columns:
        grp_cust = df.loc[df["D_CustomerData"] == 1, dep_var].dropna()
        grp_no_cust = df.loc[df["D_CustomerData"] == 0, dep_var].dropna()
        if len(grp_cust) >= 2 and len(grp_no_cust) >= 2:
            u_stat, u_p = stats.mannwhitneyu(grp_cust, grp_no_cust, alternative="two-sided")
            print(f"\n  【Mann-Whitney U 檢定: 涉及顧客個資 vs. 未涉及】")
            print(f"    涉及個資 (N={len(grp_cust)}):  平均 = {grp_cust.mean():.3f}%, 中位數 = {grp_cust.median():.3f}%")
            print(f"    未涉及 (N={len(grp_no_cust)}): 平均 = {grp_no_cust.mean():.3f}%, 中位數 = {grp_no_cust.median():.3f}%")
            print(f"    U = {u_stat:.1f}, p = {u_p:.4f}")
            results["customer_data_vs_not"] = {"U": u_stat, "p": u_p}

    return results


# ══════════════════════════════════════════════════════════════
#  Phase 5: RQ3 — 橫斷面 OLS 迴歸
# ══════════════════════════════════════════════════════════════

def test_rq3(df):
    """RQ3: 企業特徵對衝擊程度的調節效果 (OLS)"""
    print("\n" + "=" * 70)
    print("  🔬 RQ3: 橫斷面 OLS 迴歸分析")
    print("=" * 70)

    dep_var = "CAR_3d"

    # ── Model A: 攻擊特徵模型 ──
    print("\n  ── Model A: 攻擊特徵對 CAR 的影響 ──")
    indep_a = ["D_Ransomware", "D_CredentialStuffing", "D_SupplyChain"]
    if "D_ERP_Down" in df.columns:
        indep_a.append("D_ERP_Down")
    if "D_CustomerData" in df.columns:
        indep_a.append("D_CustomerData")

    df_a = df[[dep_var] + indep_a].dropna()
    if len(df_a) >= len(indep_a) + 3:
        X_a = sm.add_constant(df_a[indep_a])
        model_a = sm.OLS(df_a[dep_var], X_a).fit(cov_type="HC1")
        print(model_a.summary().tables[1].as_text())
        print(f"  R² = {model_a.rsquared:.4f}, Adj R² = {model_a.rsquared_adj:.4f}, F-stat p = {model_a.f_pvalue:.4f}")
    else:
        model_a = None
        print("  ⚠️ 樣本量不足，無法執行此迴歸。")

    # ── Model B: 企業財務特徵模型 ──
    print("\n  ── Model B: 企業財務特徵對 CAR 的影響 ──")
    indep_b = ["D_Ransomware", "D_TWSE", "淨值比_num"]
    optional_b = ["本益比_num", "Disclosure_Lag", "Volume_Shock"]
    for col in optional_b:
        if col in df.columns:
            indep_b.append(col)

    df_b = df[[dep_var] + indep_b].dropna()
    if len(df_b) >= len(indep_b) + 3:
        X_b = sm.add_constant(df_b[indep_b])
        model_b = sm.OLS(df_b[dep_var], X_b).fit(cov_type="HC1")
        print(model_b.summary().tables[1].as_text())
        print(f"  R² = {model_b.rsquared:.4f}, Adj R² = {model_b.rsquared_adj:.4f}, F-stat p = {model_b.f_pvalue:.4f}")
    else:
        model_b = None
        print("  ⚠️ 樣本量不足（含 N/A 的財務欄位較多），無法執行此迴歸。")

    # ── Model C: 完整模型 (Parsimonious) ──
    print("\n  ── Model C: 精簡完整模型 ──")
    indep_c = ["D_Ransomware", "D_CustomerData", "D_TWSE", "淨值比_num"]
    df_c = df[[dep_var] + [c for c in indep_c if c in df.columns]].dropna()
    indep_c_actual = [c for c in indep_c if c in df_c.columns]
    if len(df_c) >= len(indep_c_actual) + 3:
        X_c = sm.add_constant(df_c[indep_c_actual])
        model_c = sm.OLS(df_c[dep_var], X_c).fit(cov_type="HC1")
        print(model_c.summary().tables[1].as_text())
        print(f"  R² = {model_c.rsquared:.4f}, Adj R² = {model_c.rsquared_adj:.4f}, F-stat p = {model_c.f_pvalue:.4f}")
    else:
        model_c = None
        print("  ⚠️ 樣本量不足。")

    return {"model_a": model_a, "model_b": model_b, "model_c": model_c}


# ══════════════════════════════════════════════════════════════
#  Phase 6: RQ4 — 事前資訊外洩檢驗
# ══════════════════════════════════════════════════════════════

def test_rq4(df):
    """RQ4: 事前是否有資訊外洩跡象？"""
    print("\n" + "=" * 70)
    print("  🔬 RQ4: 事前資訊外洩檢驗 — CAR[-3, -1]")
    print("=" * 70)

    data = df["CAR_pre"].dropna()
    n = len(data)
    mean = data.mean()
    std = data.std()
    se = std / np.sqrt(n)
    t_stat, p_two = stats.ttest_1samp(data, 0)
    p_one = p_two / 2 if t_stat < 0 else 1 - p_two / 2

    try:
        w_stat, w_p = stats.wilcoxon(data, alternative="two-sided")
    except Exception:
        w_stat, w_p = np.nan, np.nan

    sig = ""
    if p_two < 0.01: sig = "***"
    elif p_two < 0.05: sig = "**"
    elif p_two < 0.10: sig = "*"

    print(f"\n  CAR[-3, -1] (事前外洩檢驗):")
    print(f"    N = {n}, 平均 = {mean:.3f}%, SE = {se:.3f}%")
    print(f"    t = {t_stat:.4f}, p (雙尾) = {p_two:.4f} {sig}")
    print(f"    p (單尾, H₁: μ<0) = {p_one:.4f}")
    print(f"    Wilcoxon W = {w_stat:.1f}, p = {w_p:.4f}" if not np.isnan(w_stat) else "    Wilcoxon: 樣本不足")
    print(f"    中位數 = {data.median():.3f}%, 正值比例 = {(data > 0).mean()*100:.1f}%")

    # 列出事前異常波動超過 2% 的案例
    anomalies = df.loc[df["CAR_pre"].abs() > 2, ["公司名稱_clean", "股票代碼", "CAR_pre", "公開揭露日"]].copy()
    if len(anomalies) > 0:
        print(f"\n  ⚠️ 事前異常波動 |CAR[-3,-1]| > 2% 的案例 ({len(anomalies)} 筆):")
        for _, row in anomalies.iterrows():
            direction = "↘ 提前下跌" if row["CAR_pre"] < 0 else "↗ 提前上漲"
            print(f"    {row['公司名稱_clean']} ({row['股票代碼']}) {row['公開揭露日']}: CAR_pre = {row['CAR_pre']:.2f}% ({direction})")

    return {"N": n, "mean": mean, "t": t_stat, "p_two": p_two}


# ══════════════════════════════════════════════════════════════
#  Phase 7: 視覺化
# ══════════════════════════════════════════════════════════════

def generate_charts(df):
    """產出分析圖表"""
    print("\n" + "=" * 70)
    print("  📈 視覺化圖表生成中...")
    print("=" * 70)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("資安事件對股價衝擊分析 (Event Study Results)", fontsize=15, fontweight="bold", y=0.98)

    # ── Chart 1: AR 與 CAR 分布直方圖 ──
    ax1 = axes[0, 0]
    ar_data = df["AR_1d"].dropna()
    car_data = df["CAR_3d"].dropna()
    ax1.hist(ar_data, bins=12, alpha=0.6, color="#4A90D9", edgecolor="white", label="AR[+1]")
    ax1.hist(car_data, bins=12, alpha=0.5, color="#E5533C", edgecolor="white", label="CAR[0,+3]")
    ax1.axvline(x=0, color="#333", linestyle="--", linewidth=1, alpha=0.7)
    ax1.axvline(x=ar_data.mean(), color="#4A90D9", linestyle="-", linewidth=1.5, alpha=0.8,
                label=f"AR mean={ar_data.mean():.2f}%")
    ax1.axvline(x=car_data.mean(), color="#E5533C", linestyle="-", linewidth=1.5, alpha=0.8,
                label=f"CAR mean={car_data.mean():.2f}%")
    ax1.set_xlabel("Abnormal Return (%)")
    ax1.set_ylabel("Frequency")
    ax1.set_title("AR & CAR Distribution")
    ax1.legend(fontsize=8)

    # ── Chart 2: 攻擊類型 vs. CAR 箱型圖 ──
    ax2 = axes[0, 1]
    box_data = []
    box_labels = []
    for label, col in [("Ransomware", "D_Ransomware"), ("Data Breach", "D_DataBreach"),
                        ("Credential\nStuffing", "D_CredentialStuffing"),
                        ("Supply\nChain", "D_SupplyChain")]:
        if col in df.columns:
            grp = df.loc[df[col] == 1, "CAR_3d"].dropna()
            if len(grp) > 0:
                box_data.append(grp.values)
                box_labels.append(f"{label}\n(N={len(grp)})")

    if box_data:
        try:
            bp = ax2.boxplot(box_data, tick_labels=box_labels, patch_artist=True, widths=0.5)
        except TypeError:
            bp = ax2.boxplot(box_data, labels=box_labels, patch_artist=True, widths=0.5)
        colors = ["#E5533C", "#4A90D9", "#F5A623", "#7ED321"]
        for patch, color in zip(bp["boxes"], colors[:len(bp["boxes"])]):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
    ax2.axhline(y=0, color="#333", linestyle="--", linewidth=1, alpha=0.7)
    ax2.set_ylabel("CAR[0,+3] (%)")
    ax2.set_title("CAR by Attack Type")

    # ── Chart 3: 淨值比 vs. CAR 散佈圖 ──
    ax3 = axes[1, 0]
    scatter_df = df[["淨值比_num", "CAR_3d"]].dropna()
    if len(scatter_df) > 3:
        colors_scatter = np.where(scatter_df["CAR_3d"] < 0, "#E5533C", "#4A90D9")
        ax3.scatter(scatter_df["淨值比_num"], scatter_df["CAR_3d"],
                    c=colors_scatter, alpha=0.7, s=60, edgecolors="white", linewidths=0.5)
        # 趨勢線
        z = np.polyfit(scatter_df["淨值比_num"], scatter_df["CAR_3d"], 1)
        p = np.poly1d(z)
        x_line = np.linspace(scatter_df["淨值比_num"].min(), scatter_df["淨值比_num"].max(), 50)
        ax3.plot(x_line, p(x_line), "--", color="#888", linewidth=1.2, alpha=0.8)
        ax3.axhline(y=0, color="#333", linestyle="--", linewidth=1, alpha=0.5)
    ax3.set_xlabel("Price-to-Book Ratio (PB)")
    ax3.set_ylabel("CAR[0,+3] (%)")
    ax3.set_title("PB Ratio vs. CAR")

    # ── Chart 4: 個別事件 CAR 瀑布圖 ──
    ax4 = axes[1, 1]
    plot_df = df[["公司名稱_clean", "股票代碼", "CAR_3d"]].dropna().copy()
    plot_df = plot_df.sort_values("CAR_3d")
    bar_labels = [f"{row['股票代碼']}" for _, row in plot_df.iterrows()]
    bar_colors = ["#E5533C" if v < 0 else "#4A90D9" for v in plot_df["CAR_3d"]]
    ax4.barh(range(len(plot_df)), plot_df["CAR_3d"], color=bar_colors, alpha=0.75, edgecolor="white")
    ax4.set_yticks(range(len(plot_df)))
    ax4.set_yticklabels(bar_labels, fontsize=7)
    ax4.axvline(x=0, color="#333", linestyle="--", linewidth=1)
    ax4.set_xlabel("CAR[0,+3] (%)")
    ax4.set_title("CAR by Company (Sorted)")

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    chart_path = os.path.join(OUTPUT_DIR, "event_study_results.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  ✅ 圖表已儲存: {chart_path}")

    return chart_path


# ══════════════════════════════════════════════════════════════
#  Phase 8: 穩健性檢驗
# ══════════════════════════════════════════════════════════════

def robustness_checks(df):
    """穩健性檢驗：排除極端值後重跑 RQ1"""
    print("\n" + "=" * 70)
    print("  🔬 穩健性檢驗 (Robustness Checks)")
    print("=" * 70)

    # 排除 CAR 絕對值超過 10% 的極端案例
    car_data = df["CAR_3d"].dropna()
    extreme_mask = car_data.abs() > 10
    n_extreme = extreme_mask.sum()
    car_trimmed = car_data[~extreme_mask]

    print(f"\n  1. 排除極端值 (|CAR| > 10%) 後的 CAAR 檢定")
    print(f"     排除 {n_extreme} 筆極端案例，剩餘 {len(car_trimmed)} 筆")
    if len(car_trimmed) >= 3:
        t_stat, p_val = stats.ttest_1samp(car_trimmed, 0)
        print(f"     CAAR = {car_trimmed.mean():.3f}%, t = {t_stat:.4f}, p = {p_val:.4f}")

    # Winsorize at 5th/95th percentile
    from scipy.stats.mstats import winsorize
    car_wins = winsorize(car_data, limits=[0.05, 0.05])
    t_stat_w, p_val_w = stats.ttest_1samp(car_wins, 0)
    print(f"\n  2. Winsorized (5%/95%) CAAR 檢定")
    print(f"     CAAR = {np.mean(car_wins):.3f}%, t = {t_stat_w:.4f}, p = {p_val_w:.4f}")

    # 排除重複受駭企業
    df_unique = df.drop_duplicates(subset=["股票代碼"], keep="first")
    car_unique = df_unique["CAR_3d"].dropna()
    if len(car_unique) >= 3:
        t_stat_u, p_val_u = stats.ttest_1samp(car_unique, 0)
        print(f"\n  3. 排除重複企業 (僅保留首次事件) 後的 CAAR 檢定")
        print(f"     N = {len(car_unique)}, CAAR = {car_unique.mean():.3f}%, t = {t_stat_u:.4f}, p = {p_val_u:.4f}")


# ══════════════════════════════════════════════════════════════
#  Phase 9: 彙整報告輸出
# ══════════════════════════════════════════════════════════════

def export_results_summary(df, rq1, rq2, rq3, rq4, chart_path):
    """輸出結構化的結果摘要 CSV"""
    summary_rows = []

    # RQ1 結果
    for label, vals in rq1.items():
        summary_rows.append({
            "研究問題": "RQ1",
            "檢定項目": f"CAAR {label}",
            "樣本數": vals["N"],
            "估計值": f"{vals['CAAR']:.3f}%",
            "t 統計量": f"{vals['t']:.4f}",
            "p 值(雙尾)": f"{vals['p_two']:.4f}",
            "顯著性": vals["sig"]
        })

    # RQ4 結果
    summary_rows.append({
        "研究問題": "RQ4",
        "檢定項目": "CAAR[-3,-1] 事前外洩",
        "樣本數": rq4["N"],
        "估計值": f"{rq4['mean']:.3f}%",
        "t 統計量": f"{rq4['t']:.4f}",
        "p 值(雙尾)": f"{rq4['p_two']:.4f}",
        "顯著性": "***" if rq4["p_two"] < 0.01 else ("**" if rq4["p_two"] < 0.05 else ("*" if rq4["p_two"] < 0.10 else ""))
    })

    summary_df = pd.DataFrame(summary_rows)
    summary_path = os.path.join(OUTPUT_DIR, "hypothesis_test_results.csv")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ 假說檢定結果已匯出: {summary_path}")

    # 輸出清理後的分析資料集
    analysis_cols = [
        "公司名稱_clean", "股票代碼", "市場別", "公開揭露日", "攻擊類型",
        "AR_1d", "CAR_3d", "CAR_pre", "Volume_Shock",
        "D_Ransomware", "D_DataBreach", "D_CredentialStuffing",
        "D_Unauthorized", "D_SupplyChain", "D_ERP_Down", "D_CustomerData",
        "D_TWSE", "Disclosure_Lag", "D_Repeat",
        "本益比_num", "殖利率_num", "淨值比_num"
    ]
    available_cols = [c for c in analysis_cols if c in df.columns]
    clean_path = os.path.join(OUTPUT_DIR, "analysis_dataset_clean.csv")
    df[available_cols].to_csv(clean_path, index=False, encoding="utf-8-sig")
    print(f"  ✅ 清理後分析資料集已匯出: {clean_path}")


# ══════════════════════════════════════════════════════════════
#  主程式入口
# ══════════════════════════════════════════════════════════════

def run_analysis(csv_path=None):
    """執行完整分析流程"""
    print("\n" + "═" * 70)
    print("  🚀 資安事件對股價衝擊 — 事件研究法統計分析")
    print("     Event Study: Cybersecurity Incidents & Stock Price Impact")
    print("═" * 70)

    # 1. 載入與清洗
    df = load_and_clean(csv_path)
    print(f"\n  載入完成: {len(df)} 筆事件, {df['股票代碼'].nunique()} 家不同企業")

    # 2. 描述性統計
    desc = descriptive_statistics(df)

    # 3. RQ1
    rq1 = test_rq1(df)

    # 4. RQ2
    rq2 = test_rq2(df)

    # 5. RQ3
    rq3 = test_rq3(df)

    # 6. RQ4
    rq4 = test_rq4(df)

    # 7. 穩健性檢驗
    robustness_checks(df)

    # 8. 視覺化
    chart_path = generate_charts(df)

    # 9. 匯出結果
    export_results_summary(df, rq1, rq2, rq3, rq4, chart_path)

    print("\n" + "═" * 70)
    print("  ✅ 全部分析流程完成！")
    print(f"  📁 結果輸出目錄: {OUTPUT_DIR}")
    print("═" * 70)

    return df, rq1, rq2, rq3, rq4


if __name__ == "__main__":
    run_analysis()
