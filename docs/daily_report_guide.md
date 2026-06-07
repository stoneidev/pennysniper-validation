# `daily_report.py` Developer Guide

> 일일 시그널 스캐너 + HTML 리포트 생성기.
> 나중에 코드 수정할 때 참고용 상세 문서.

위치: `scripts/live/daily_report.py`

---

## 🎯 What This Script Does

1. `config/current_rule.json`에서 현재 활성 룰을 읽음
2. `data/daily_cache/*.csv`의 모든 종목 일봉 캐시를 순회
3. **as-of 날짜 기준** 시그널 조건을 만족하는 종목을 탐지 (look-ahead bias 없음)
4. `reports/YYYY-MM-DD.html` 생성 (예쁜 다크 테마 HTML)
5. `reports/index.html` 자동 갱신 (월별 그룹화 + summary 링크)

---

## 📥 Inputs

### 1. Rule file: `config/current_rule.json`

자동 생성됨 (by `monthly_retrain.py`). 형식:

```json
{
  "cons_d": 60,                          // 횡보 기간 (trading days)
  "entry_lo": 1.20,                      // 진입 최소가
  "entry_hi": 1.50,                      // 진입 최대가
  "tp_ratio": 1.50,                      // 익절 배수 (1.50 = +50%)
  "hold_d": 30,                          // 최대 보유 일수
  "valid_until": "2026-06-30",           // 룰 만료일
  "trained_on_period": "2026-03-01_2026-06-01",
  "train_n": 3,                          // 학습 시 사용된 시그널 수
  "train_win_rate": 1.0,
  "train_mean_return": 0.48,
  "generated_at": "2026-06-07T19:24:00"
}
```

### 2. Daily cache: `data/daily_cache/*.csv`

각 ticker별 CSV. 필수 컬럼:
```
Date,Open,High,Low,Close,Volume
2025-06-01,0.95,1.10,0.94,0.99,2500000
...
```

`fetch_universe.py`가 자동 갱신.
`_meta.json`은 메타데이터 (필터링 시 제외 대상, prefix `_`).

### 3. CLI 인자

```bash
python scripts/live/daily_report.py [--as-of YYYY-MM-DD] [--rule-file PATH]
```

| 인자 | 기본값 | 의미 |
|---|---|---|
| `--as-of` | `today` | 스캔 기준일. 과거 백테스트 시 사용 |
| `--rule-file` | `config/current_rule.json` | 룰 JSON 경로 |

---

## 📤 Outputs

### 1. `reports/YYYY-MM-DD.html`

해당 날짜의 시그널 리포트. 구조:
- Header (제목 + 날짜 + nav)
- Active Rule 카드 (key/value + 학습 메타 태그)
- Signal banner (녹색 = 시그널 있음, 회색 = 없음)
- Signals table (시그널 있을 때만)
- Trade Plan (시그널 있을 때만)
- Footer (면책)

### 2. `reports/index.html`

전체 리포트 인덱스. 자동 재생성.
- Summaries 섹션 (`_*.html` 파일들)
- 월별 그룹화 (YYYY-MM)
- 날짜 역순 정렬

---

## 🔍 Signal Detection Logic (핵심)

`detect_signals(rule, as_of)` 함수가 실행:

### 종목별 검사 (각 CSV)

```python
for f in CACHE.glob("*.csv"):
    sym = f.stem
    df = parse_csv(f)              # CSV 로드 + sort by Date
    df = df[df["Date"] <= as_of]   # ⭐ 핵심: 미래 데이터 제거 (look-ahead 방지)

    if len(df) < cons_d + 2:
        continue
```

### 5가지 조건 모두 만족해야 시그널

```python
last = df.iloc[-1]            # as_of 또는 직전 trading day
prev = df.iloc[-2]
last_close = last["Close"]
prev_close = prev["Close"]

# 조건 1: 마지막 bar가 as_of (또는 4일 이내)
if last["Date"] != as_of and (as_of - last["Date"]).days > 4:
    continue   # 너무 오래된 데이터는 시그널 무효

# 조건 2: 오늘 종가가 [entry_lo, entry_hi) 범위
if not (entry_lo <= last_close < entry_hi):
    continue

# 조건 3: 어제 종가는 entry_lo 미만 (= 오늘이 첫 돌파)
if prev_close >= entry_lo:
    continue

# 조건 4: 직전 cons_d일 종가 모두 < $1.00 (횡보)
prior = df["Close"].values[-(cons_d + 1):-1]
if not (prior < 1.0).all():
    continue
if not (prior > 0).all():     # 0 또는 음수 가격 방어
    continue

# 조건 5: 횡보 기간 평균 거래량 ≥ 10,000
if df["Volume"].values[-(cons_d + 1):-1].mean() < MIN_AVG_VOL:
    continue

# 통과 → 시그널!
signals.append({...})
```

**왜 이 5가지인가:**
1. 데이터 신선도 (휴장 후 너무 오래되면 무효)
2. 진입 가격대 (룰이 정의)
3. 어제까지는 안 돌파 = 오늘이 진짜 첫 돌파
4. 충분한 횡보 (catalyst 없는 정상 매도 압력 소진)
5. 거래량 (delisting 직전 zombie 종목 제외)

---

## 🛠️ Customization Points

수정하고 싶을 때 어디 손 댈지:

### A. 시그널 조건 변경

`detect_signals()` 함수 안에서 조건 추가/변경.

**예: SL 추가하기**
```python
# 새 룰 필드: rule["sl_ratio"] (예: 0.95 = -5% SL)
# detect는 그대로, 출력 단에 SL 추가
```

**예: 갭업 필터 추가**
```python
# 조건 5 다음에:
gap = last_close / prev_close
if gap > 1.50:  # 50% 이상 갭업 제외
    continue
```

**예: 거래량 비율 조건**
```python
# 직전 5일 평균 vs 60일 평균
recent_vol = df["Volume"].values[-5:].mean()
if recent_vol < cons_avg_vol * 1.5:  # 1.5배 미만이면 stale
    continue
```

### B. 진입가 컬럼 변경

기본은 "다음날 시초가" 가정. 시그널 자체에선 안 보임. **render_html의 trade plan**에서 표시:

```python
# 현재
"Place market BUY at the OPEN of the next trading day"

# 변경 예: 시그널 일자 종가 진입
"Place market BUY at signal-day CLOSE"
```

### C. 출력 컬럼 추가

`render_html()` 함수의 signals table 부분:

```python
# 현재 컬럼: Symbol, Today Close, Prev Close, Cons Avg, TP Target

# 추가하려면 detect_signals()에서 데이터 채우고:
signals.append({
    "symbol": sym,
    "today_close": last_close,
    "prev_close": prev_close,
    "consolidation_avg": float(prior.mean()),
    "consolidation_avg_vol": float(...),
    # NEW: 60일 동안 최저가
    "cons_min": float(prior.min()),
    # NEW: 거래량 급증 비율
    "vol_ratio": float(last["Volume"] / prior_vol.mean()),
})

# render_html()의 signal_rows 생성 부분에 컬럼 추가:
signal_rows = ... f"""
  <td class="num">${s['cons_min']:.2f}</td>
  <td class="num">{s['vol_ratio']:.1f}x</td>
"""
```

### D. CSS / 디자인 변경

`CSS` 변수 (파일 상단):
- `--bg`, `--panel`, `--text`, `--accent`, `--green`, `--red` 등 색상
- `.container { max-width: 980px }` 너비
- `.banner.signal` (시그널 발견 배너) 스타일
- `.kv` (key/value 격자) 스타일

### E. 상수 (파일 상단)

```python
MIN_AVG_VOL = 10_000   # 횡보 기간 최소 평균 거래량
                       # 값을 올리면 더 보수적 (zombie 제외 강화)
                       # 값을 내리면 신호 더 많이 잡힘
```

---

## 🧩 Internal Functions (참고)

```python
parse_csv(path)         # CSV → DataFrame, 35행 미만이면 None
detect_signals(rule, as_of)  # 메인 시그널 감지
render_html(rule, as_of, signals, out_path)  # HTML 렌더링
update_index()          # reports/index.html 자동 생성
main()                  # CLI entrypoint
```

### `update_index()` 동작

```python
# reports/ 안의 파일들을 분류:
# 1. 날짜 형식 (YYYY-MM-DD.html) → 월별 그룹화
# 2. _* 형식 (예: _may_2025_summary.html, _weekly_2026-W23.html) → "Summaries"

# 월별 카드를 역순(최신 우선)으로 출력
```

새 summary 파일 추가 시 자동 인식 (예: `_quarter_2026_q2.html` 만들면 자동 link).

---

## 🐛 Common Issues & Debugging

### "No new breakout signals" 가 항상 뜸

확인 순서:
1. `data/daily_cache/`에 파일 있는가?
2. 캐시가 최신인가? (`_meta.json`의 `last_fetch` 확인)
3. 룰 진입 범위가 너무 좁은가? (`entry_lo`/`entry_hi` 확인)
4. as_of 날짜가 휴장일?

테스트:
```bash
# 디버그용: 한 종목 시그널 직접 시뮬레이션
python -c "
import pandas as pd
df = pd.read_csv('data/daily_cache/CTMX.csv', parse_dates=['Date'])
df = df[df['Date'] <= '2025-05-08'].sort_values('Date')
print(df.tail(35))
"
```

### 시그널이 너무 많이 잡힘

룰을 더 엄격하게:
- `cons_d` 증가 (30 → 60)
- 진입 범위 좁히기 ($1.05-$1.50 → $1.20-$1.50)
- `MIN_AVG_VOL` 증가 (10K → 50K)

### HTML 렌더링 깨짐

특수문자 escape 누락 가능. `html.escape()` 적용 확인:
```python
html.escape(s["symbol"])   # 항상 HTML escape
html.escape(rule.get("trained_on_period", "?"))
```

### Index에 새 파일이 안 보임

`update_index()`가 호출되었는지 확인:
```python
# main() 마지막
update_index()
```

또는 수동:
```bash
python -c "import sys; sys.path.insert(0,'scripts/live'); from daily_report import update_index; update_index()"
```

---

## 🔄 Manual Run Examples

### 오늘 시그널 스캔 (현재 룰)

```bash
python scripts/live/daily_report.py
# → reports/2026-06-07.html
```

### 특정 과거 날짜 backtest (look-ahead 없음)

```bash
python scripts/live/daily_report.py --as-of 2025-05-08
# → reports/2025-05-08.html
# 그 시점 ≤ 데이터만 사용해서 시뮬레이션
```

### 다른 룰로 비교

```bash
# 분기별 룰로 5월 8일 검증
python scripts/live/daily_report.py \
  --as-of 2025-05-08 \
  --rule-file config/rule_2025_q2.json
```

### 한 달 통째로 backfill

```bash
# 5월 2025 전체 (도우미 스크립트)
python scripts/live/generate_may_reports.py
python scripts/live/may_summary.py
```

---

## 🔗 관련 파일

| 파일 | 역할 | 호출 관계 |
|---|---|---|
| `fetch_universe.py` | 일봉 캐시 갱신 | upstream |
| `monthly_retrain.py` | 룰 재최적화 | upstream |
| **`daily_report.py`** | **본 가이드 대상** | — |
| `weekly_report.py` | 주간 종합 (daily 결과 파싱) | downstream |
| `*_summary.py` | 월간 종합 helpers | downstream |

---

## 🚦 Test Before Push (체크리스트)

코드 수정 후:

```bash
# 1. 시그널이 있던 과거 날짜로 sanity check
python scripts/live/daily_report.py --as-of 2025-05-08
open reports/2025-05-08.html
# → CTMX/JBDI 2건 보이면 OK

# 2. 시그널이 없던 날짜로 empty case 확인
python scripts/live/daily_report.py --as-of 2025-05-01
open reports/2025-05-01.html
# → "No new breakout signals" 표시되면 OK

# 3. 오늘 날짜
python scripts/live/daily_report.py
open reports/$(date +%Y-%m-%d).html

# 4. index 갱신 확인
open reports/index.html
```

---

## ⚙️ GH Action에서 어떻게 호출되는가

`.github/workflows/daily_breakout_scan.yml`:

```yaml
- name: Run daily scanner & generate report
  run: |
    if [ -n "${{ github.event.inputs.as_of_date }}" ]; then
      python scripts/live/daily_report.py --as-of "${{ github.event.inputs.as_of_date }}"
    else
      python scripts/live/daily_report.py
    fi
```

매 평일 06:00 UTC 자동 실행. workflow_dispatch로 수동 trigger 시 `as_of_date` 입력 가능.

---

## 🔐 Constraints (지키면 좋을 규칙)

1. **Look-ahead 방지**: `df = df[df["Date"] <= as_of]` 절대 빼지 말 것
2. **Backward compatible JSON**: rule 필드 추가 OK, 제거 시 default 처리
3. **Idempotent**: 같은 as-of 다시 돌리면 같은 결과
4. **No side effects outside repo**: 외부 API 호출 금지 (fetch는 별도 스크립트)
5. **HTML escape**: 모든 사용자/티커 데이터에 `html.escape()` 적용

---

## 📚 Related Docs

- [README.md](../README.md) — 전체 시스템 개요
- [scripts/live/README.md](../scripts/live/README.md) — 운영 스크립트 묶음
- [validation_journey.md](validation_journey.md) — 룰을 어떻게 발견했나
