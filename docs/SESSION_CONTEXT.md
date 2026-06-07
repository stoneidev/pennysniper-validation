# Session Context — Resume Guide

> **이 문서는 다음 세션(Claude 또는 다른 협업자)에서 작업을 이어가기 위한
> 전체 컨텍스트 스냅샷입니다.** 가장 먼저 이걸 읽고 시작하세요.

**Last updated:** 2026-06-07 (KST)
**Last commit:** `b242b81 — Add Telegram notifications (Option B)` by KIM JONG IL

---

## 1. TL;DR — 현재 시스템이 무엇을 하고 있는가

매일 자동으로 NASDAQ 페니스탁 universe를 스캔해서 breakout 시그널을 감지하고,
HTML 리포트를 GitHub Pages에 publish하며, Telegram으로 알림까지 보내는
**adaptive walk-forward 시스템**.

- **Repo:** https://github.com/stoneidev/pennysniper-validation (PUBLIC)
- **Live site:** https://stoneidev.github.io/pennysniper-validation/
- **Telegram bot:** https://t.me/Pennysniper_alert_bot
- **GH Action:** 매 평일 + 매주 토요일 자동 실행

---

## 2. 어떻게 여기까지 왔나 (4-Phase 요약)

원래 시작점: **PRD v3.0 — KNN+RL 기반 페니스탁 day trading**

총 **23개 가설**을 정밀 검증한 결과:

| Phase | 가설 | 결과 |
|---|---|---|
| 1 | 페니스탁 단기 1~15 (뉴스, momentum, gap, sector 등) | 모두 음수 알파 |
| 2 | BTC funding arb / XRP mean rev / RL walk-forward | BTC +5%, XRP +48% (naive), RL **−999%** (실패) |
| 3 | 페니스탁 breakout (cons + first breakout) | **+** Selection bias 통제 후도 양수 |
| 4 | 운영 시스템 구축 (rolling adaptive) | **현재 운영 중** |

**핵심 결론:**
- 단순 룰이 RL을 압도 (XRP에서 +48% vs −999%)
- 매월 재학습이 분기별보다 +52% 좋음 (₩28M vs ₩18M)
- **현재 룰: monthly retrain로 적응형**

자세한 일지: **`docs/validation_journey.md`**

---

## 3. 현재 운영 중인 룰

`config/current_rule.json` (자동 갱신, 매월 1일):

```json
{
  "cons_d": 60,
  "entry_lo": 1.20,
  "entry_hi": 1.50,
  "tp_ratio": 1.50,
  "hold_d": 30,
  "valid_until": "2026-06-30",
  "trained_on_period": "2026-03-01_2026-06-01",
  "train_n": 3,
  "train_win_rate": 1.0,
  "train_mean_return": 0.48
}
```

**의미:** 직전 60 trading days 종가 모두 < $1.00 → 오늘 종가 $1.20~$1.50 사이 첫 돌파 → 다음날 시초가 매수 → +50% 도달 시 TP 청산 또는 30일 후 강제 청산.

**다음 재학습:** 2026-07-01 (자동, GH Action에서 직전 3개월 = 2026.04~06 데이터로 그리드 서치)

---

## 4. 시스템 구성 (4-Layer Pipeline)

자세한 SVG: `docs/assets/architecture.svg`

```
┌── ① Triggers (cron) ──────────────────────────────────────┐
│                                                          │
│  Daily         Tue~Sat 06:00 UTC (KST 15:00)            │
│  Monthly       1st of month (embedded in daily)         │
│  Weekly        Saturday 07:00 UTC (KST 16:00)           │
│                                                          │
└──────────────────────────────────────────────────────────┘
                           ↓
┌── ② Live Scripts (scripts/live/) ────────────────────────┐
│                                                          │
│  fetch_universe.py     — yfinance, incremental ~3min   │
│  monthly_retrain.py    — 그리드 서치, 매월 1일          │
│  daily_report.py       — 시그널 탐지 + HTML 작성        │
│  weekly_report.py      — 주간 종합 + 시장 인사이트     │
│  positions.py          — CLI 거래 기록 (수동)          │
│  positions_report.py   — 포지션 P&L HTML (auto)        │
│  telegram_notify.py    — 일일 Telegram 알림            │
│  telegram_weekly.py    — 주간 Telegram 알림            │
│                                                          │
└──────────────────────────────────────────────────────────┘
                           ↓
┌── ③ Data Stores (committed to git) ──────────────────────┐
│                                                          │
│  data/daily_cache/{TICKER}.csv  — 1,400+ tickers       │
│  data/positions.json            — 거래 기록 (현재 빈값)  │
│  config/current_rule.json       — 활성 룰              │
│  reports/*.html                 — 자동 생성 페이지     │
│                                                          │
└──────────────────────────────────────────────────────────┘
                           ↓
┌── ④ Publishing ──────────────────────────────────────────┐
│                                                          │
│  git commit + push (3-retry on race)                    │
│  GitHub Pages 자동 배포                                  │
│  Telegram 알림 발송                                      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 5. 모든 GitHub Secrets

| Secret | 용도 | 상태 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot API 인증 | ✅ 등록됨 (2026-06-07) |
| `TELEGRAM_CHAT_ID` | 메시지 보낼 chat | ✅ 등록됨 (`7538691225`) |

**Secret 값 (필요 시 재등록용 — 다음 세션에서 새로 발급 권장):**
- `TELEGRAM_BOT_TOKEN`: 노출됨 (대화 history에 있음). 보안상 BotFather에서 `/revoke` 후 새 token 발급 권장.
- `TELEGRAM_CHAT_ID`: `7538691225` (개인 chat, Rex Kim)
- Bot username: `@Pennysniper_alert_bot`

**재등록 명령:**
```bash
echo "<NEW_TOKEN>" | gh secret set TELEGRAM_BOT_TOKEN -R stoneidev/pennysniper-validation
echo "7538691225" | gh secret set TELEGRAM_CHAT_ID -R stoneidev/pennysniper-validation
```

---

## 6. Git 설정 (이 repo에서 직접 commit 시)

```bash
# 이미 설정되어 있음 (이 repo 한정 local config)
git config user.name   # → KIM JONG IL
git config user.email  # → nijin39@gmail.com
```

만약 새 clone에서 작업한다면 다시 설정 필요:
```bash
git config user.name "KIM JONG IL"
git config user.email "nijin39@gmail.com"
```

GH Action commit은 별도로 `github-actions[bot]` 사용.

---

## 7. Repository Structure

```
pennysniper-validation/
├── README.md                          ← 운영 시스템 가이드 (architecture-first)
├── docs/
│   ├── SESSION_CONTEXT.md             ← 본 파일 (resume guide)
│   ├── validation_journey.md          ← 23 가설 검증 일지
│   ├── findings.md                    ← 가설별 정밀 결과
│   ├── rolling_adaptive_findings.md   ← 적응형 발견
│   ├── optimal_rule_2026_watchlist.md
│   ├── stooq_full_universe_findings.md
│   ├── 2026_signals_watchlist.md      ← Warrant 함정
│   ├── scripts_overview.md            ← 모든 스크립트 한눈에 (개발자용)
│   ├── daily_report_guide.md          ← daily_report.py 상세
│   ├── assets/
│   │   └── architecture.svg
│   └── PRD_v3.0.md                    ← 원본 PRD (archive)
├── scripts/
│   ├── live/                          ← 운영 (★)
│   │   ├── fetch_universe.py
│   │   ├── monthly_retrain.py
│   │   ├── daily_report.py
│   │   ├── weekly_report.py
│   │   ├── positions.py               ← CLI
│   │   ├── positions_report.py
│   │   ├── telegram_notify.py         ← 일일 알림
│   │   ├── telegram_weekly.py         ← 주간 알림
│   │   ├── may_summary.py             ← helpers (월간 종합)
│   │   ├── may_2026_summary.py
│   │   ├── june_2026_summary.py
│   │   ├── generate_may_reports.py    ← 백필 helpers
│   │   ├── generate_may_2026_reports.py
│   │   ├── generate_june_2026_reports.py
│   │   ├── import_stooq_cache.py      ← 1회용
│   │   └── README.md
│   ├── breakout/                      ← 백테스트 검증 코드 (Phase 3)
│   ├── pennysniper/                   ← Phase 1 가설 1~15
│   ├── btc/                           ← Phase 2
│   └── xrp/                           ← Phase 2
├── data/
│   ├── daily_cache/                   ← 1,400+ ticker CSVs
│   └── positions.json                 ← 거래 기록 (지금 빈값)
├── config/
│   ├── current_rule.json              ← 활성 룰 (월별 자동 갱신)
│   ├── rule_2025_q2.json              ← 백필용
│   └── rule_2026_q2.json
├── reports/                           ← HTML 출력
│   ├── index.html
│   ├── 2025-05-01.html ~ 2026-06-...
│   ├── _may_2025_summary.html
│   ├── _may_2026_summary.html
│   ├── _june_2026_summary.html
│   ├── _weekly_2026-W23.html
│   └── _positions.html
├── results/                           ← 백테스트 raw outputs
│   ├── csv/
│   └── plots/
├── .github/workflows/
│   ├── daily_breakout_scan.yml        ← 매 평일 (Tue~Sat)
│   └── weekly_report.yml              ← 매주 토요일
├── requirements.txt
├── LICENSE                            ← MIT
└── .gitignore
```

---

## 8. 자동화 스케줄 (UTC / KST)

| 시점 (UTC) | 시점 (KST) | 작업 |
|---|---|---|
| 매 평일 (Tue~Sat) 06:00 | 15:00 | 일일 스캔 + 리포트 + Telegram |
| 매월 1일 (06:00 UTC) | 15:00 | 월간 룰 재학습 (daily 안에서) |
| 매주 토요일 07:00 | 16:00 | 주간 리포트 + Telegram |

**Manual trigger:**
```bash
# 일일 스캔 (특정 날짜 backtest 가능)
gh workflow run daily_breakout_scan.yml -R stoneidev/pennysniper-validation \
  -f as_of_date=2026-06-15

# 주간 리포트
gh workflow run weekly_report.yml -R stoneidev/pennysniper-validation
```

---

## 9. Local 환경 셋업 (다음 세션에서)

```bash
cd /Users/stoni/Downloads/pennysniper_validation

# venv 활성화 (이미 만들어져 있음)
source venv/bin/activate

# 의존성 (이미 설치됨)
# pip install -r requirements.txt

# 현재 상태 확인
git status
git log -5 --oneline
cat config/current_rule.json
cat data/daily_cache/_meta.json
```

### 일반 작업 명령어 모음

```bash
# 현재 룰로 오늘 시그널 스캔
python scripts/live/daily_report.py
open reports/$(date +%Y-%m-%d).html

# 과거 날짜 backtest
python scripts/live/daily_report.py --as-of 2025-05-08

# 새 월 시작 시 룰 재학습 (자동이지만 수동도 가능)
python scripts/live/monthly_retrain.py

# 주간 리포트
python scripts/live/weekly_report.py
open reports/_weekly_$(python -c "import pandas as pd; t=pd.Timestamp.now(); y,w,_=t.isocalendar(); print(f'{y}-W{w:02d}')").html

# 거래 기록
python scripts/live/positions.py buy NTCL --price 1.02 --shares 100 --note "..."
python scripts/live/positions.py sell NTCL --price 1.53 --reason tp_hit
python scripts/live/positions.py status
python scripts/live/positions_report.py

# Telegram 테스트 (secrets export 후)
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="7538691225"
python scripts/live/telegram_notify.py

# 캐시 갱신 (필요 시)
python scripts/live/fetch_universe.py
```

---

## 10. 미해결 항목 / 다음에 할 만한 것

### 시스템 작동 확인 후
- [ ] **첫 자동 실행 결과 확인** — 다음 평일 (Tue 2026-06-09 KST 15:00) GH Action 실행 후 Telegram 메시지 도착 확인
- [ ] **첫 주간 리포트** — 다음 토요일 (2026-06-13 KST 16:00) 자동 발송 확인

### 보안
- [ ] **Telegram bot token revoke + 재발급** (현재 token은 대화 history에 노출됨)
- [ ] BotFather에서 `/revoke` 후 새 token으로 GH Secrets 갱신

### 기능 추가 후보
- [ ] **시그널 → 자동 paper trade 기록** (positions.json에 자동 buy entry 추가)
- [ ] **숏 포지션 추적** (현재 long only)
- [ ] **다른 거래소 universe** (NYSE, AMEX 추가)
- [ ] **Slippage 동적 계산** (지금은 2% 고정)
- [ ] **Stop-loss 추가** (현재 SL 없음, 백테스트가 SL 도움 안 됨이라 결론)
- [ ] **시그널 종목 차트 SVG** (Telegram 메시지에 미니 chart 첨부)

### 검증 강화
- [ ] **2018-2022 약세장 데이터로 OOS** (현재 강세장 + meme mania 시기만 검증)
- [ ] **세금 22% 반영한 보수적 시뮬**
- [ ] **여러 universe 동시 운영** (NASDAQ + AMEX)

### 운영 강화
- [ ] **6개월 paper trading 후 실전 결정**
- [ ] **소액 ($500-$1000) live 시작 시 broker API 연동** (Alpaca 권장)

---

## 11. 알려진 한계 (지키면서 작업할 것)

1. **In-sample bias** — 그리드 서치 결과가 실전에서 약화될 수 있음
2. **Selection bias** — yfinance에 살아있는 종목만 (delisted 제외)
3. **Slippage** — 페니스탁 실제 5~10%, 백테스트는 2% 가정
4. **세금** — 한국 양도세 22% 미반영
5. **GH Action 무료 tier** — 월 2,000분, 현재 사용 ~10분/평일 + 5분/토요일 = 월 ~250분 (충분)
6. **yfinance rate limit** — 분당 ~100 종목, incremental은 문제 없음
7. **시그널 빈도 감소 추세** — 시장 효율화로 매년 줄어들 가능성

---

## 12. 자주 헷갈리는 것

### Q: 매월 재학습이라는데 daily_breakout_scan.yml에서 어떻게 작동?
A: workflow 안에 conditional step 있음:
```yaml
- name: Determine if monthly retrain needed
  run: |
    DAY=$(date -u +%d)
    if [ "$DAY" = "01" ]; then
      echo "retrain=true" >> $GITHUB_OUTPUT
    elif [ valid_until 만료 ]; then
      echo "retrain=true" >> $GITHUB_OUTPUT
    fi

- name: Monthly retrain (if needed)
  if: steps.retrain_check.outputs.retrain == 'true'
  run: python scripts/live/monthly_retrain.py
```

별도 `monthly_retrain.yml` 워크플로 없음.

### Q: positions.json 비어있는데 리포트는 어떻게 나오는가?
A: 빈 상태에서도 빈 테이블 + "missed signals" 섹션 표시. 거래 시작하면 자동 채워짐. CLI로 buy/sell 기록만 하면 됨.

### Q: Bot token 다시 보고 싶다
A: BotFather에 `/mybots` → `Pennysniper_alert_bot` → `API Token` 클릭. 또는 새로 발급 (`/revoke`).

### Q: GitHub Pages 배포 안 됨
A: Settings → Pages → Source: "GitHub Actions" 확인. 첫 배포 후 5~10분 캐시 가능.

### Q: GH Action 실패 시
A: https://github.com/stoneidev/pennysniper-validation/actions 에서 로그 확인.
가장 흔한 원인:
1. yfinance API rate limit → 다음 실행에서 자동 복구
2. git push 충돌 → 이미 retry 로직 있음 (3회)
3. Telegram 실패 → 워크플로 안 깨짐 (silent skip)

---

## 13. 다음 세션 시작 체크리스트

새 세션 시작 시 이 순서로:

1. **이 문서 (SESSION_CONTEXT.md) 먼저 읽기**
2. `git pull` (마지막 자동 commit 확인)
3. `git log --oneline -5` (최근 변경사항 파악)
4. `ls reports/ | tail -10` (최근 리포트 확인)
5. https://github.com/stoneidev/pennysniper-validation/actions (자동 실행 상태)
6. https://stoneidev.github.io/pennysniper-validation/ (live 상태)

문제 있으면:
- **GH Action 실패** → workflow 로그 확인
- **Telegram 안 옴** → secrets 확인 (`gh secret list`)
- **Pages 안 보임** → Pages settings + Action artifact 확인

---

## 14. 외부 리소스

- **GitHub repo**: https://github.com/stoneidev/pennysniper-validation
- **Live site**: https://stoneidev.github.io/pennysniper-validation/
- **Telegram bot**: https://t.me/Pennysniper_alert_bot
- **Telegram Bot API docs**: https://core.telegram.org/bots/api
- **yfinance docs**: https://github.com/ranaroussi/yfinance
- **NASDAQ symbol list**: https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt

---

## 15. 핵심 파일 절대경로

```
/Users/stoni/Downloads/pennysniper_validation/                  ← repo root
├── README.md
├── docs/SESSION_CONTEXT.md                                     ← 본 파일
├── docs/validation_journey.md                                  ← 검증 일지
├── docs/scripts_overview.md                                    ← 스크립트 가이드
├── docs/daily_report_guide.md                                  ← daily_report 상세
├── scripts/live/*.py                                           ← 운영 스크립트들
├── config/current_rule.json                                    ← 활성 룰
├── data/daily_cache/                                           ← 1,400+ 캐시
├── data/positions.json                                         ← 거래 기록 (현재 빈값)
└── reports/                                                    ← HTML 출력
```

---

## 16. 마지막 commit 시점 시스템 상태

| 항목 | 값 |
|---|---|
| **Last commit** | `b242b81` (2026-06-07) |
| **Author** | KIM JONG IL <nijin39@gmail.com> |
| **Cached tickers** | 1,480 |
| **Reports** | 5월 2025 (22) + 5월 2026 (21) + 6월 2026 (22) + 주간 W23 (1) + 월간 종합 (3) + positions (1) |
| **Active rule** | 60d cons / $1.20-$1.50 / TP +50% / 30d hold (valid until 2026-06-30) |
| **Open positions** | 0 |
| **Closed trades** | 0 |
| **Telegram** | 작동 확인됨 (msg_id 4까지 전송) |
| **GH Pages** | https://stoneidev.github.io/pennysniper-validation/ (live) |
| **Repo visibility** | PUBLIC |

---

이 문서가 다음 세션에서 컨텍스트를 빠르게 복원하는 핵심 자료입니다.
시스템 변경 시 이 문서도 업데이트하세요.
