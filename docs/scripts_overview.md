# Live Scripts Overview

> `scripts/live/` 안의 모든 스크립트 한눈에. 자세한 가이드는 각 링크 참조.

---

## 🗺️ Pipeline Diagram

```
┌─────────────────┐
│ fetch_universe  │ ① yfinance에서 일봉 fetch (incremental)
│   .py           │   data/daily_cache/{TICKER}.csv 갱신
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ monthly_retrain │ ② 매월 1일 룰 재최적화
│   .py           │   config/current_rule.json 갱신
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ daily_report    │ ③ 매 평일 시그널 탐지
│   .py           │   reports/YYYY-MM-DD.html
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ weekly_report   │ ④ 매 토요일 주간 종합
│   .py           │   reports/_weekly_YYYY-WW.html
└─────────────────┘
```

---

## 📋 스크립트 한 줄 요약

| 스크립트 | 실행 주기 | 역할 | 가이드 |
|---|---|---|---|
| `fetch_universe.py` | 매일 (GH Action) | yfinance NASDAQ 일봉 fetch | [link](#fetch_universepy) |
| `monthly_retrain.py` | 매월 1일 (auto) | 직전 3개월 데이터로 룰 그리드 search | [link](#monthly_retrainpy) |
| **`daily_report.py`** | **매 평일 (GH Action)** | **시그널 탐지 + HTML 리포트** | **[full guide](daily_report_guide.md)** |
| `weekly_report.py` | 매 토요일 (GH Action) | 주간 종합 + 시장 인사이트 | [link](#weekly_reportpy) |
| `import_stooq_cache.py` | 1회 (수동) | Stooq 로컬 데이터 → daily_cache | [link](#import_stooq_cachepy) |
| `generate_may_reports.py` | 1회 (수동) | 5월 2025 backfill | helper |
| `generate_may_2026_reports.py` | 1회 (수동) | 5월 2026 backfill | helper |
| `generate_june_2026_reports.py` | 1회 (수동) | 6월 2026 backfill | helper |
| `may_summary.py` | 1회 (수동) | 5월 2025 종합 | helper |
| `may_2026_summary.py` | 1회 (수동) | 5월 2026 종합 | helper |
| `june_2026_summary.py` | 1회 (수동) | 6월 2026 종합 | helper |

---

## fetch_universe.py

**Inputs:** `nasdaqtrader.com` 심볼 리스트 + 기존 `data/daily_cache/`

**Outputs:** `data/daily_cache/{TICKER}.csv`, `data/daily_cache/_meta.json`

**Behavior:**
- 캐시 있으면 incremental (직전 5일 이내면 ~10일 overlap만 fetch)
- 캐시 없거나 stale (5일+) 이면 250일 full refresh
- Warrant/Right/Unit (`W`/`R`/`U`/`Z`) 접미사 제외
- Penny range filter: 1년 동안 한 번이라도 $0.30~$5.00 거래된 종목만 캐시

**주요 상수 (수정 시):**
```python
LOOKBACK_DAYS_FULL = 250          # initial seed
LOOKBACK_DAYS_INCREMENTAL = 10    # daily update overlap
INCREMENTAL_TRIGGER_DAYS = 5      # threshold to switch to incremental
PRICE_MIN = 0.30
PRICE_MAX = 5.00
```

**Runtime:**
- Initial seed: ~25 min (3,000+ tickers)
- Incremental update: ~3 min

**수동 실행:**
```bash
python scripts/live/fetch_universe.py
```

---

## monthly_retrain.py

**Inputs:** `data/daily_cache/`

**Outputs:** `config/current_rule.json` (overwrite)

**Behavior:**
1. 현재 시점 또는 `--as-of` 기준 월 시작 결정
2. 직전 3개월 데이터로 그리드 서치:
   - cons_d ∈ {30, 45, 60}
   - entry_range ∈ {$1.05-1.15, $1.05-1.20, $1.10-1.30, $1.20-1.50}
   - tp_ratio ∈ {1.10, 1.15, 1.20, 1.30, 1.50}
   - hold ∈ {30, 60, 90}
3. Score = `win_rate × (1 + max(p10, -1))`
4. 1위 조합을 `config/current_rule.json`에 저장

**중요:** TP/SL 조합 그리드를 수정하려면 상수 변경:
```python
CONS_DAYS_LIST = [30, 45, 60]        # 새 값 추가/제거 가능
ENTRY_RANGES = [...]
TP_LEVELS = [1.10, 1.15, 1.20, 1.30, 1.50]
HOLDS = [30, 60, 90]
MIN_AVG_VOL = 10_000
```

**수동 실행:**
```bash
# 오늘 기준
python scripts/live/monthly_retrain.py

# 과거 시점 룰을 학습 (백테스트용)
python scripts/live/monthly_retrain.py --as-of 2025-04-15 --out config/rule_2025_q2.json
```

**output JSON 형식:** [daily_report_guide.md#1-rule-file](daily_report_guide.md#1-rule-file-configcurrent_rulejson) 참조.

---

## daily_report.py

**Full guide:** **[daily_report_guide.md](daily_report_guide.md)**

핵심:
- 매일 종목별 5가지 조건으로 시그널 탐지
- HTML 리포트 생성 (다크 테마)
- `reports/index.html` 자동 갱신

수정 시 가장 자주 손대는 곳:
1. `detect_signals()` — 시그널 조건
2. `render_html()` — HTML 출력 형식
3. `CSS` 변수 — 디자인

---

## weekly_report.py

**Inputs:** `reports/YYYY-MM-DD.html` (지난 7일치) + `data/daily_cache/`

**Outputs:** `reports/_weekly_YYYY-WW.html`

**Behavior:**
1. 이번 ISO week의 daily 리포트들에서 시그널 추출
2. 각 시그널의 실제 결과 resolve (price cache 보고)
3. Market regime 분류 (Active / Normal / Quiet / No breakouts)
4. 누적 통계 (시작 이후 모든 시그널)
5. 자동 인사이트 생성 (승률 변화, holding 알림 등)

**Sections:**
- Market Regime
- This Week stats (4-card grid)
- Active Rule
- Cumulative stats
- Signal table
- Insights (자동 생성 callout)

**수정 포인트:**
```python
# Regime 분류 임계값
def regime_tag(week_signals_count, ...):
    if week_signals_count >= 5:  # 변경 가능
        return ("Active breakout regime", ...)
    if week_signals_count >= 2:
        return ("Normal regime", ...)
    ...
```

```python
# Insights 추가 규칙
insights = []
if week_win >= 0.8:
    insights.append(("pos", "승률 80%+ — 룰이 시장과 잘 맞음"))
# 새 인사이트 추가:
if cum_total_pct < 0:
    insights.append(("neg", "누적 음수 — 룰 재검토 필요"))
```

**수동 실행:**
```bash
python scripts/live/weekly_report.py
```

---

## import_stooq_cache.py

**1회용 helper.** Stooq에서 로컬 다운로드한 daily archive를 `data/daily_cache/` 형식으로 변환.

**용도:** 초기 seed (yfinance 5,000 종목 × 30분 대신 Stooq archive로 빠르게 시작)

**Behavior:**
- `/Users/stoni/Downloads/data/daily/us/nasdaq stocks/` 스캔
- Stooq 형식 (`<DATE>` 등 `<>` 컬럼) → `Date,Open,High,Low,Close,Volume`
- Penny range 필터 (한 번이라도 $0.30~$5)
- Warrant/Right/Unit 제외

**수동 실행 (필요 시 1회):**
```bash
python scripts/live/import_stooq_cache.py
```

이미 한 번 실행했음. yfinance 데이터가 cumulative 갱신되므로 다시 실행할 일 거의 없음.

---

## *_summary.py 파일들

월간/주간 종합 helpers. **각 스크립트는 한 달 데이터에 특화** 되어 있음 (히스토리컬 backfill용).

| 파일 | 대상 |
|---|---|
| `may_summary.py` | 2025년 5월 |
| `may_2026_summary.py` | 2026년 5월 |
| `june_2026_summary.py` | 2026년 6월 |

**왜 따로 있나:** 룰이 매월 다르므로 각 시기에 맞는 룰 파일을 명시적으로 사용. 학습 메타정보 (`trained_on_period` 등) 포함된 summary 카드 생성.

**미래 월 추가 시:**
1. `generate_july_2026_reports.py` 생성 (run loop)
2. `july_2026_summary.py` 생성 (aggregation)
3. 또는 `weekly_report.py`처럼 generic하게 `monthly_summary.py`로 통합 (TODO)

---

## ⚙️ Constants Cheatsheet (모든 스크립트 공통)

| 상수 | 위치 | 의미 |
|---|---|---|
| `MIN_AVG_VOL = 10_000` | 다수 | 횡보기간 평균 거래량 최소 |
| `SLIP = 0.02` | 다수 | round-trip 슬리피지 가정 (2%) |
| `PRICE_MIN/MAX` | fetch_universe | universe 가격 범위 |
| `LOOKBACK_DAYS_FULL = 250` | fetch_universe | full fetch 일수 |
| `EXCLUDE_SUFFIX = ("W","R","U","Z")` | 다수 | warrant 등 제외 |
| `CONS_DAYS_LIST` | retrain | 그리드 검색 횡보 기간 |
| `ENTRY_RANGES` | retrain | 그리드 검색 진입 범위 |
| `TP_LEVELS` | retrain | 그리드 검색 익절 |
| `HOLDS` | retrain | 그리드 검색 보유 기간 |

---

## 🚨 깨지면 어디부터 보나

### 시그널이 안 나옴
1. `data/daily_cache/_meta.json`의 `last_fetch` 확인
2. CSV 직접 열어보기 (`data/daily_cache/AACG.csv`)
3. `daily_report.py --as-of 2025-05-08` (시그널 있던 날짜) 테스트

### Index가 빈 페이지
1. `update_index()` 호출됐나?
2. `reports/` 안의 HTML 파일들 권한 확인

### Weekly가 cumulative 0
1. `reports/`에 daily HTML 파일들 있나?
2. `parse_signals_from_html()`의 정규식이 daily HTML 형식과 맞나?
3. CSS 변경 시 HTML 구조도 바뀌면 정규식 깨짐 — 주의

### GH Action 푸시 충돌
- 이미 retry + rebase 로직 있음
- 그래도 실패 시: 로컬에서 `git pull --rebase` 후 재시도

---

## 🔗 더 보기

- [daily_report_guide.md](daily_report_guide.md) — daily_report.py 상세
- [validation_journey.md](validation_journey.md) — 왜 이 룰을 쓰는가
- [README.md](../README.md) — 전체 시스템
- [scripts/live/README.md](../scripts/live/README.md) — 사용법 (cron 등)
