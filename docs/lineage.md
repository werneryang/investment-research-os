# 研究依赖清单

由 `uv run iros lineage --md docs/lineage.md` 生成，不要手改；网站页面 `lineage.html` 在每次构建时重新生成。方法与信号见 `src/investment_os/lineage.py` 开头的说明。

- 研究 36 项；模块 49 个（计算 31、取数 11、脚本 7）；数据集 87 个；已接入来源 9 个
- 从任何研究都到达不了：38 项（其中模块与脚本 7 个）
- 断链：0 处

## 1. 信号覆盖

| 信号 | 覆盖研究数 |
|---|---|
| 研究分支 | 36 / 36 |
| 数据集（data） | 36 / 36 |
| 运行框架 | 36 / 36 |
| 登记引用（method） | 7 / 36 |

所有研究还经过运行框架 `runs.py` 调用的这些计算模块（下文不在每项研究下重复）：`research/findings.py`、`validation/reference.py`

## 2. 每项研究的依赖链

### 2 项研究（分支 asset_history，依赖相同）

研究：`us_asset_history`、`us_asset_history_last_25y`

- 研究分支：`research/asset_history.py`
- 数据·annual：`damodaran_histret`
  - 来源：`Damodaran 数据`
  - 接入器：`connectors/damodaran.py`
- 数据·cpi（可选）：`fred_cpiaucsl`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·monthly_market（可选）：`french_ff3`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·long_real（可选）：`shiller_real`
  - 来源：`Shiller 股市数据`
  - 接入器：`connectors/shiller.py`
- 数据·tbill_check（可选）：`fred_dtb3`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`

### 芯片经营分析：NVIDIA 与 Micron 的分部营收与利润

研究：`chip_operations_p3b`

- 研究分支：`research/chip.py`
  - 导入：`research/feasibility.py`
- 登记·units：`config/supply_chain/units.yaml`
- 数据·evidence：`chip_segment_evidence`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/evidence.py`
  - 生成者：`supply_chain/bundle.py`
    - 导入：`data/fundamentals.py`
      - 导入：`connectors/sec.py`
    - 导入：`supply_chain/catalog.py`
      - 读取登记：`config/supply_chain`
    - 导入：`supply_chain/classification.py`
    - 读取登记：`config/fundamentals.yaml`
    - 读取登记：`config/supply_chain`

### 16 项研究（分支 company，依赖相同）

研究：`company_alphabet`、`company_amazon`、`company_apple`、`company_berkshire`、`company_coca-cola`、`company_costco`、`company_exxon`、`company_johnson-johnson`、`company_jpmorgan`、`company_microsoft`、`company_nike`、`company_nvidia`、`company_procter-gamble`、`company_sample`、`company_tesla`、`company_walmart`

- 研究分支：`research/company.py`
- 数据·facts：`company_sec_facts`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/evidence.py`
  - 生成者：`scripts/prepare_company_research.py`
    - 导入：`data/fundamentals.py`
      - 导入：`connectors/sec.py`
    - 导入：`research/company.py`
    - 读取登记：`config/company-research.yaml`

### 2 项研究（分支 curve_attribution，依赖相同）

研究：`ust_curve_attribution_2024`、`ust_curve_attribution_last_year`

- 研究分支：`research/curve_attribution.py`
  - 导入：`analytics/rates.py`
  - 导入：`tenor.py`
  - 导入：`validation/crosscheck.py`
- 数据·curve：`ust_par_yield_curve`
  - 来源：`Treasury 利率数据`
  - 接入器：`connectors/treasury.py`
    - 导入：`tenor.py`
- 数据·real：`fred_dfii10`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·breakeven：`fred_t10yie`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·policy：`fred_dff`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·cross_check（可选）：`fred_dgs10`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·cpi（可选）：`fred_cpiaucsl`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·fed_assets（可选）：`fred_walcl`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`

### Alphabet：2026 年第三季度财报研究

研究：`earnings_googl_2026q3`

- 研究分支：`research/earnings_quarter.py`
  - 导入：`earnings/__init__.py`
    - 导入：`events/__init__.py`
      - 导入：`supply_chain/catalog.py`
        - 读取登记：`config/supply_chain`
      - 读取登记：`config/events`
    - 读取登记：`config/earnings`
- 登记·earnings：`config/earnings/googl_2026q3.yaml`
- 数据·evidence：`earnings_evidence`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/evidence.py`
  - 生成者：`earnings/__init__.py`
    - 导入：`events/__init__.py`
      - 导入：`supply_chain/catalog.py`
        - 读取登记：`config/supply_chain`
      - 读取登记：`config/events`
    - 读取登记：`config/earnings`

### NVIDIA：2027 财年第三季度财报研究

研究：`earnings_nvda_fy27q3`

- 研究分支：`research/earnings_quarter.py`
  - 导入：`earnings/__init__.py`
    - 导入：`events/__init__.py`
      - 导入：`supply_chain/catalog.py`
        - 读取登记：`config/supply_chain`
      - 读取登记：`config/events`
    - 读取登记：`config/earnings`
- 登记·earnings：`config/earnings/nvda_fy27q3.yaml`
- 数据·evidence：`earnings_evidence`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/evidence.py`
  - 生成者：`earnings/__init__.py`
    - 导入：`events/__init__.py`
      - 导入：`supply_chain/catalog.py`
        - 读取登记：`config/supply_chain`
      - 读取登记：`config/events`
    - 读取登记：`config/earnings`

### Tesla：2026 年第三季度财报研究

研究：`earnings_tsla_2026q3`

- 研究分支：`research/earnings_quarter.py`
  - 导入：`earnings/__init__.py`
    - 导入：`events/__init__.py`
      - 导入：`supply_chain/catalog.py`
        - 读取登记：`config/supply_chain`
      - 读取登记：`config/events`
    - 读取登记：`config/earnings`
- 登记·earnings：`config/earnings/tsla_2026q3.yaml`
- 数据·evidence：`earnings_evidence`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/evidence.py`
  - 生成者：`earnings/__init__.py`
    - 导入：`events/__init__.py`
      - 导入：`supply_chain/catalog.py`
        - 读取登记：`config/supply_chain`
      - 读取登记：`config/events`
    - 读取登记：`config/earnings`

### NVIDIA 首席执行官离任与回任：事实与时间线

研究：`event_nvda_ceo_transition_2026`

- 研究分支：`research/event_timeline.py`
- 登记·event：`config/events/nvda_ceo_transition_2026.yaml`
- 数据·evidence：`event_evidence`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/evidence.py`
  - 生成者：`events/__init__.py`
    - 导入：`supply_chain/catalog.py`
      - 读取登记：`config/supply_chain`
    - 读取登记：`config/events`

### 美国 12 行业的长期回报、风险与经济背景

研究：`us_industry_12`

- 研究分支：`research/industry.py`
  - 导入：`analytics/industry.py`
- 数据·returns：`french_ind12_vw`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·equal_weight：`french_ind12_ew`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·firms：`french_ind12_firms`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·size：`french_ind12_size`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·bm：`french_ind12_bm`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·annual_check：`french_ind12_annual`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·ff3：`french_ff3`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·ff5：`french_ff5`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·momentum：`french_mom`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·cpi：`fred_cpiaucns`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvam：`fred_rvam`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_usmine：`fred_usmine`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvar：`fred_rvar`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvaw：`fred_rvaw`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_ustrade：`fred_ustrade`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvai：`fred_rvai`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_usinfo：`fred_usinfo`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvama：`fred_rvama`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_manemp：`fred_manemp`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_awhaeman：`fred_awhaeman`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_ces3000000003：`fred_ces3000000003`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_ipman：`fred_ipman`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_mcumfn：`fred_mcumfn`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·recession：`fred_usrec`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·policy_rate：`fred_dff`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·oil_price：`fred_dcoilwtico`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`

### 美国 49 行业的长期回报、风险与经济背景

研究：`us_industry_49`

- 研究分支：`research/industry.py`
  - 导入：`analytics/industry.py`
- 数据·returns：`french_ind49_vw`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·equal_weight：`french_ind49_ew`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·firms：`french_ind49_firms`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·size：`french_ind49_size`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·bm：`french_ind49_bm`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·annual_check：`french_ind49_annual`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·ff3：`french_ff3`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·ff5：`french_ff5`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·momentum：`french_mom`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·cpi：`fred_cpiaucns`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·recession：`fred_usrec`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·policy_rate：`fred_dff`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`

### 美国行业：经济、盈利、估值与指引专题

研究：`us_industry_dossier`

- 研究分支：`research/industry.py`
  - 导入：`analytics/industry.py`
- 数据·returns：`french_ind12_vw`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·equal_weight：`french_ind12_ew`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·firms：`french_ind12_firms`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·size：`french_ind12_size`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·bm：`french_ind12_bm`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·annual_check：`french_ind12_annual`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·ff3：`french_ff3`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·ff5：`french_ff5`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·momentum：`french_mom`
  - 来源：`Kenneth French 数据库`
  - 接入器：`connectors/french.py`
- 数据·cpi：`fred_cpiaucns`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvam：`fred_rvam`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_usmine：`fred_usmine`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvar：`fred_rvar`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvaw：`fred_rvaw`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_ustrade：`fred_ustrade`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvai：`fred_rvai`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_usinfo：`fred_usinfo`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_rvama：`fred_rvama`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_manemp：`fred_manemp`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_awhaeman：`fred_awhaeman`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_ces3000000003：`fred_ces3000000003`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_ipman：`fred_ipman`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·econ_mcumfn：`fred_mcumfn`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·fundamentals：`industry_sec_facts`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/evidence.py`
  - 生成者：`scripts/prepare_industry.py`
  - 声明的生成脚本：`scripts/build_industry_fundamentals.py`
    - 读取登记：`config/fundamentals.yaml`
    - 读取登记：`config/industry.yaml`
- 数据·valuation：`industry_valuation`
  - 来源：`Damodaran 数据`
  - 接入器：`connectors/evidence.py`
  - 生成者：`scripts/prepare_industry.py`
  - 声明的生成脚本：`scripts/prepare_industry_cases.py`
    - 读取登记：`config/industry-guidance.yaml`
- 数据·guidance：`industry_guidance`
  - 来源：`公司投资者关系公告`
  - 接入器：`connectors/evidence.py`
  - 生成者：`scripts/prepare_industry.py`
  - 声明的生成脚本：`scripts/prepare_industry_cases.py`
    - 读取登记：`config/industry-guidance.yaml`
- 数据·recession：`fred_usrec`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·policy_rate：`fred_dff`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`
- 数据·oil_price：`fred_dcoilwtico`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`

### 假设平价国债的利率敏感性情景

研究：`ust_par_bond_rate_risk`

- 研究分支：`research/par_bond.py`
  - 导入：`analytics/bonds.py`
  - 导入：`analytics/rates.py`
  - 导入：`tenor.py`
- 数据·curve：`ust_par_yield_curve`
  - 来源：`Treasury 利率数据`
  - 接入器：`connectors/treasury.py`
    - 导入：`tenor.py`

### 2 项研究（分支 rates_curve，依赖相同）

研究：`ust_curve_2024`、`ust_curve_last_year`

- 研究分支：`research/rates_curve.py`
  - 导入：`analytics/rates.py`
  - 导入：`tenor.py`
  - 导入：`validation/crosscheck.py`
- 数据·curve：`ust_par_yield_curve`
  - 来源：`Treasury 利率数据`
  - 接入器：`connectors/treasury.py`
    - 导入：`tenor.py`
- 数据·cross_check（可选）：`fred_dgs10`
  - 来源：`FRED API / ALFRED`
  - 接入器：`connectors/fred.py`

### 美国炼油利用率、裂解价差与炼油公司股东总收益（2016–2025 年）

研究：`us_refining_investment_2016_2025`

- 研究分支：`research/refining_investment.py`
  - 导入：`analytics/rounding.py`
  - 导入：`research/feasibility.py`
- 数据·utilization：`eia_refinery_utilization`
  - 来源：`EIA 石油数据`
  - 接入器：`connectors/eia.py`
- 数据·crude：`eia_spot_wti_cushing`
  - 来源：`EIA 石油数据`
  - 接入器：`connectors/eia.py`
- 数据·gasoline：`eia_spot_gasoline_gulf`
  - 来源：`EIA 石油数据`
  - 接入器：`connectors/eia.py`
- 数据·distillate：`eia_spot_ulsd_gulf`
  - 来源：`EIA 石油数据`
  - 接入器：`connectors/eia.py`
- 数据·tsr_valero：`sec_tsr_valero`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/sec_graph.py`
    - 导入：`connectors/sec.py`
- 数据·tsr_pbf：`sec_tsr_pbf`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/sec_graph.py`
    - 导入：`connectors/sec.py`

### 2 项研究（分支 refining_throughput，依赖相同）

研究：`us_refining_throughput_scenarios_2025`、`us_refining_utilization_2025`

- 研究分支：`research/refining.py`
  - 导入：`analytics/constraints.py`
  - 导入：`analytics/rounding.py`
  - 导入：`research/feasibility.py`
- 数据·inputs：`eia_refinery_gross_inputs`
  - 来源：`EIA 石油数据`
  - 接入器：`connectors/eia.py`
- 数据·capacity：`eia_refinery_operable_capacity`
  - 来源：`EIA 石油数据`
  - 接入器：`connectors/eia.py`
- 数据·utilization：`eia_refinery_utilization`
  - 来源：`EIA 石油数据`
  - 接入器：`connectors/eia.py`

### 2 项研究（分支 relation_chain，依赖相同）

研究：`chip_relation_chain_intc`、`chip_relation_chain_nvda`

- 研究分支：`research/relation_chain.py`
  - 导入：`supply_chain/chain.py`
- 登记·root：`config/supply_chain/entities.yaml`
- 登记·downstream_notes：`config/supply_chain/claims.yaml`
- 数据·evidence：`relation_chain_evidence`
  - 来源：`SEC EDGAR`
  - 接入器：`connectors/evidence.py`
  - 生成者：`supply_chain/relation_bundle.py`
    - 导入：`data/fundamentals.py`
      - 导入：`connectors/sec.py`
    - 导入：`supply_chain/catalog.py`
      - 读取登记：`config/supply_chain`
    - 导入：`supply_chain/classification.py`
    - 读取登记：`config/supply_chain`

## 3. 模块被多少研究用到

| 模块 | 类型 | 研究数 |
|---|---|---|
| `analytics/rates.py` | 计算 | 36 |
| `research/findings.py` | 计算 | 36 |
| `validation/reference.py` | 计算 | 36 |
| `connectors/evidence.py` | 取数 | 24 |
| `connectors/sec.py` | 取数 | 20 |
| `data/fundamentals.py` | 取数 | 19 |
| `research/company.py` | 计算 | 16 |
| `scripts/prepare_company_research.py` | 脚本 | 16 |
| `connectors/fred.py` | 取数 | 9 |
| `supply_chain/catalog.py` | 计算 | 7 |
| `connectors/french.py` | 取数 | 5 |
| `connectors/treasury.py` | 取数 | 5 |
| `tenor.py` | 计算 | 5 |
| `events/__init__.py` | 计算 | 4 |
| `research/feasibility.py` | 计算 | 4 |
| `validation/crosscheck.py` | 计算 | 4 |
| `analytics/industry.py` | 计算 | 3 |
| `analytics/rounding.py` | 计算 | 3 |
| `connectors/eia.py` | 取数 | 3 |
| `earnings/__init__.py` | 计算 | 3 |
| `research/earnings_quarter.py` | 计算 | 3 |
| `research/industry.py` | 计算 | 3 |
| `supply_chain/classification.py` | 计算 | 3 |
| `analytics/constraints.py` | 计算 | 2 |
| `connectors/damodaran.py` | 取数 | 2 |
| `connectors/shiller.py` | 取数 | 2 |
| `research/asset_history.py` | 计算 | 2 |
| `research/curve_attribution.py` | 计算 | 2 |
| `research/rates_curve.py` | 计算 | 2 |
| `research/refining.py` | 计算 | 2 |
| `research/relation_chain.py` | 计算 | 2 |
| `supply_chain/chain.py` | 计算 | 2 |
| `supply_chain/relation_bundle.py` | 计算 | 2 |
| `analytics/bonds.py` | 计算 | 1 |
| `connectors/sec_graph.py` | 取数 | 1 |
| `research/chip.py` | 计算 | 1 |
| `research/event_timeline.py` | 计算 | 1 |
| `research/par_bond.py` | 计算 | 1 |
| `research/refining_investment.py` | 计算 | 1 |
| `supply_chain/bundle.py` | 计算 | 1 |
| `scripts/build_industry_fundamentals.py` | 脚本 | 1 |
| `scripts/prepare_industry.py` | 脚本 | 1 |
| `scripts/prepare_industry_cases.py` | 脚本 | 1 |

## 4. 来源出错会波及的研究

| 来源 | 数据集（研究数） | 受影响研究数 |
|---|---|---|
| SEC EDGAR（`sec_edgar`） | `chip_segment_evidence`（1）、`company_sec_facts`（16）、`earnings_evidence`（3）、`event_evidence`（1）、`industry_sec_facts`（1）、`relation_chain_evidence`（2）、`sec_tsr_pbf`（1）、`sec_tsr_valero`（1） | 25 |
| FRED API / ALFRED（`fred_api`） | `alfred_cpiaucsl`（0）、`alfred_gdp`（0）、`alfred_payems`（0）、`alfred_unrate`（0）、`fred_aaa10y`（0）、`fred_awhaeman`（2）、`fred_baa10y`（0）、`fred_ces3000000003`（2）、`fred_cpiaucns`（3）、`fred_cpiaucsl`（4）、`fred_dcoilwtico`（2）、`fred_dexchus`（0）、`fred_dexjpus`（0）、`fred_dexuseu`（0）、`fred_dexusuk`（0）、`fred_dff`（5）、`fred_dfii10`（2）、`fred_dgs10`（4）、`fred_dtb3`（2）、`fred_dtwexbgs`（0）、`fred_gdp`（0）、`fred_ipman`（2）、`fred_manemp`（2）、`fred_mcumfn`（2）、`fred_nasdaq100`（0）、`fred_nasdaqcom`（0）、`fred_payems`（0）、`fred_rvai`（2）、`fred_rvam`（2）、`fred_rvama`（2）、`fred_rvar`（2）、`fred_rvaw`（2）、`fred_sofr`（0）、`fred_sp500`（0）、`fred_t10yie`（2）、`fred_unrate`（0）、`fred_usinfo`（2）、`fred_usmine`（2）、`fred_usrec`（3）、`fred_ustrade`（2）、`fred_vixcls`（0）、`fred_walcl`（2） | 9 |
| Kenneth French 数据库（`ken_french`） | `french_asia_pacific_ex_japan3`（0）、`french_developed3`（0）、`french_developed_ex_us3`（0）、`french_emerging5`（0）、`french_europe3`（0）、`french_ff3`（5）、`french_ff5`（3）、`french_ind12_annual`（2）、`french_ind12_bm`（2）、`french_ind12_ew`（2）、`french_ind12_firms`（2）、`french_ind12_size`（2）、`french_ind12_vw`（2）、`french_ind49_annual`（1）、`french_ind49_bm`（1）、`french_ind49_ew`（1）、`french_ind49_firms`（1）、`french_ind49_size`（1）、`french_ind49_vw`（1）、`french_japan3`（0）、`french_mom`（3）、`french_north_america3`（0） | 5 |
| Treasury 利率数据（`ust_treasury`） | `ust_par_yield_curve`（5） | 5 |
| Damodaran 数据（`damodaran`） | `damodaran_histret`（2）、`industry_valuation`（1） | 3 |
| EIA 石油数据（`eia`） | `eia_refinery_gross_inputs`（2）、`eia_refinery_operable_capacity`（2）、`eia_refinery_utilization`（3）、`eia_spot_gasoline_gulf`（1）、`eia_spot_ulsd_gulf`（1）、`eia_spot_wti_cushing`（1） | 3 |
| Shiller 股市数据（`shiller`） | `shiller_cape`（0）、`shiller_fundamentals`（0）、`shiller_price`（0）、`shiller_real`（2） | 2 |
| 公司投资者关系公告（`company_ir`） | `industry_guidance`（1） | 1 |
| 人工导入（`manual`） | `manual_example`（0） | 0 |

## 5. 从任何研究都到达不了的模块与数据

「其他引用」说明它在研究之外是否还有用途（命令行、网站、定时取数等），供判断是否删除；本清单不作删除建议。

| 名称 | 类型 | 其他引用 |
|---|---|---|
| `analytics/returns.py` | 计算模块 | tests/test_analytics.py |
| `analytics/risk.py` | 计算模块 | tests/test_analytics.py |
| `connectors/manual.py` | 取数模块 | connectors；tests/test_connectors_ingest.py；数据集 manual_example |
| `connectors/fred.py · fred_api_vintages` | 接入器 | 数据集 alfred_cpiaucsl；数据集 alfred_gdp；数据集 alfred_payems；数据集 alfred_unrate |
| `scripts/event_window_returns.py` | 脚本 | 脚本，不被研究引用 |
| `scripts/market_drawdown_replay.py` | 脚本 | 脚本，不被研究引用 |
| `scripts/run_company_research.py` | 脚本 | 脚本，不被研究引用 |
| `alfred_cpiaucsl` | 数据集 | 网站说明 site/content.yaml |
| `alfred_gdp` | 数据集 | 网站说明 site/content.yaml |
| `alfred_payems` | 数据集 | 网站说明 site/content.yaml |
| `alfred_unrate` | 数据集 | 网站说明 site/content.yaml |
| `fred_aaa10y` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_baa10y` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_dexchus` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_dexjpus` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_dexuseu` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_dexusuk` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_dtwexbgs` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_gdp` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_nasdaq100` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_nasdaqcom` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_payems` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_sofr` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_sp500` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_unrate` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `fred_vixcls` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `french_asia_pacific_ex_japan3` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `french_developed3` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `french_developed_ex_us3` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `french_emerging5` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `french_europe3` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `french_japan3` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `french_north_america3` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `manual_example` | 数据集 | 无 |
| `shiller_cape` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `shiller_fundamentals` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `shiller_price` | 数据集 | 定时取数（scheduled_fetch）；网站说明 site/content.yaml |
| `人工导入` | 来源 | 数据集 manual_example |

另有 19 个来源没有登记数据集（候选或已停用），不算未使用。

## 6. 断链

没有断链。
