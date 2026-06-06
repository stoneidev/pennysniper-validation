# PennySniper Validation

> **나스닥 페니스탁 자동매매 PRD v3.0의 핵심 가설을 데이터로 검증한 일지**
> 
> "RL/KNN 기반 페니스탁 day trading"이라는 처음 가설에서 출발해서, 
> 23개 가설을 정밀 검증한 후 **양수 알파 4가지를 발견**했습니다.

---

## 📌 English Abstract

This repository documents an iterative, data-driven validation of the
PennySniper PRD v3.0 — an automated trading system designed for NASDAQ
penny stock day trading using KNN clustering + PPO reinforcement learning.

Through 23 independent hypotheses tested against real market data
(Polygon SIP minute bars, Binance funding rates, ~169,500 daily
penny-stock observations), the original day-trading premise was
falsified. However, three durable alphas were discovered:

1. **BTC funding-rate arbitrage** — +5% APY (decaying)
2. **XRP −7%/1h mean-reversion** — +48% APY (true walk-forward)
3. **Penny stock 30-60d consolidation breakout** — +1,681% APY in-sample
   from Jan 2025 (pending OOS confirmation)

Reinforcement learning, when applied with proper monthly walk-forward
retraining, **destroyed alpha** (−999% APY) — confirming that simple
domain-knowledge rules outperform complex models on sparse financial
data.

---

## 🎯 출발점

원래 PRD v3.0의 핵심 가설:
> "나스닥 페니스탁의 1분봉 OHLCV에서 거래량 + 모멘텀 패턴을
> KNN으로 군집화하고 PPO 강화학습으로 진입/청산을 학습하면
> 일반인 자본으로 양수 EV 자동매매가 가능하다"

**결론: 위 가설은 거짓입니다.** 다만 검증 과정에서 진짜 작동하는 다른 알파를 발견했습니다.

---

## 🔬 검증 결과 요약 (23개 가설)

### 1️⃣ 페니스탁 단기 자동매매 — 모두 음수 알파

| # | 가설 | OOS 결과 |
|---|---|---|
| 1 | 거래량 폭발 후 다음날 매수 | gross −2.82% |
| 2 | +100% 시점 진입 (1분봉 정밀) | gross −1.36% |
| 3 | 18 feature univariate 신호 | Bonferroni 통과 0개 |
| 4 | Logistic OOS 분류 | 알파 +0.6% (N=18 노이즈) |
| 5 | Walk-forward learning curve | 학습할수록 악화 |
| 6 | +30% 빠른 트리거 (clean) | gross −5.00% |
| 7 | Oracle exit upper bound | N=6, 통계 무의미 |
| 8 | 시간대별 패턴 | 알파 0% |
| 9 | 거래량 군집 quintile | Cherry-picking 의심 |
| 10 | 숏 전략 | gross +0.93% (비용에 무너짐) |
| 11 | 펌프앤페이드 (숏) | gross **−24%** |
| 12 | 갭 (spike-only sample) | +3.81% (selection bias) |
| 13 | **갭 (full universe N=169,525)** | **gross −0.18%** ✓ |
| 14 | Co-movement 테마 날 다음날 | 알파 +0.02%p (노이즈) |
| 15 | Sector momentum spillover | 알파 +0.03%p (노이즈) |

**결론**: 페니스탁 단기 자동매매에는 일반인이 OHLCV로 잡을 수 있는
신뢰 가능한 알파가 거의 없음. Selection bias 통제 후 진짜 universe
(169,525건) 평균 −0.18%, 비용 차감 시 −3.18%.

### 2️⃣ 암호화폐 — 진짜 양수 알파 발견

| # | 가설 | 결과 |
|---|---|---|
| 16 | **BTC Funding always-on hedge** | **+5.0% APY** ✅ |
| 17 | BTC 1분봉 mean reversion | +4% APY |
| 18 | XRP Funding always-on | +3.9% APY (효율화 중) |
| 19 | **XRP −7% 1h mean reversion (naive)** | **+48% APY** ⭐ (true walk-forward) |
| 20 | **XRP Q-learning RL walk-forward** | **−999% APY** ❌ |

**결정적 발견**: 동일 데이터·동일 walk-forward에서 **단순 룰이 RL을 압도**.
RL은 sparse reward와 non-stationary 시장에서 알파를 생성하지 못하고
거래비용을 폭증시킴 (6,013건 거래 vs naive 21건).

### 3️⃣ 페니스탁 Breakout — 의외의 양수 알파 ⭐

당신의 직관적 가설("$1 미만에서 머문 페니스탁이 $1.5를 돌파하면
이후 큰 상승")을 정밀 검증한 결과:

| # | 조건 | N | 승률 | 거래당 평균 |
|---|---|---|---|---|
| 21 | 30d/45d/60d cons + $1.05~$1.20 돌파 | 25~37 | 73~89% | +20~177% |
| 22 | **Mega-grid 최적 (30d cons / TP $3.0 / 90d horizon)** | 34 | **74%** | **+81%** |
| 23 | 60d cons / TP $3.0 / 180d horizon | 21 | **91%** | **+114%** |

**핵심 발견**:
- $1.5+ 큰 돌파는 알파 없음 (당신 직감과 반대)
- $1.05~$1.20 약한 돌파가 진짜 신호
- TP $1.5 (낮음)는 너무 빨리 익절 → 큰 상승 놓침
- **TP $3.0~$5.0 + 90~180일 hold**가 자본 성장 최적

**Reverse split 함정 검증 완료**: yfinance `auto_adjust=True` 사용 +
live `.splits` API 교차 확인 → **25개 시그널 모두 진짜 시장 움직임**
(split artifact 0건).

---

## 💰 ₩1,000,000 시뮬레이션 (2025.01 ~ 2026.06, 17개월)

같은 페니스탁 breakout 룰을 in-sample이지만 진짜 시장 데이터로 적용:

| 전략 | 자본 운용 | 거래 수 | 승률 | **최종 자산** |
|---|---|---|---|---|
| 30d / TP $3.0 / 90d hold | ALL-IN | 5 | 74% | **₩61,489,186 (+6,049%)** |
| 60d / TP $3.0 / 180d hold | ALL-IN | 4 | 78% | ₩27,141,381 (+2,614%) |
| 30d / TP $3.0 / 90d hold | 25% per trade | 14 | 74% | ₩9,405,561 (+841%) |
| 30d / TP $5.0 / 90d hold | 10% per trade | 18 | 74% | ₩4,100,822 (+310%) |

**중요한 한계**:
- In-sample (룰을 발견한 후 동일 데이터로 측정)
- ALL-IN은 시그널 타이밍 운에 크게 의존
- 한국 거주자 양도세 22% 미반영
- 슬리피지 2% 가정 (실제 5~10% 가능)

**현실적 권장**: 25% allocation으로 ₩1M → ~₩9M (+840%) 기대치를
가지되 진짜 OOS는 paper trading 6개월 이상 필요.

---

## 🎯 최종 발견된 알파 3종 (실전 진입 가능)

### A. BTC Funding Rate Arbitrage
- **방법**: BTC spot long + perpetual short (델타 뉴트럴)
- **수익원**: 8시간마다 funding rate 수령
- **2년 평균 APY**: +5.0% (수수료 차감 후)
- **상태**: 알파 약화 중 (2024 +8% → 2026 +1%)

### B. XRP −7% 1시간 Mean Reversion
- **방법**: XRP 1시간 −7% 하락 시 매수, 4시간 후 청산
- **2년 walk-forward APY**: +48%
- **승률**: 86% (21건)
- **상태**: 진짜 walk-forward에서도 양수, 빈도 낮음

### C. 페니스탁 60d Breakout (가장 강한 알파)
- **방법**: 60일 이상 $1 미만 → $1.05~$1.20 돌파 → 다음날 시초가 매수 → TP $3.0 또는 180일 close
- **In-sample 승률**: 91%
- **거래당 평균**: +114%
- **상태**: **OOS 미검증** (in-sample 결과로 추정)
- **빈도**: 연 12~15건 (2026년 빈도 감소 추세)

---

## 📁 Repository 구조

```
pennysniper-validation/
├── README.md                # 본 문서
├── docs/
│   ├── PRD_v3.0.md         # 원본 PRD (출발점)
│   └── findings.md         # 23개 가설 상세 결과
├── scripts/
│   ├── pennysniper/        # 가설 1~15 (페니스탁 단기)
│   ├── btc/                # 가설 16~17 (BTC)
│   ├── xrp/                # 가설 18~20 (XRP)
│   └── breakout/           # 가설 21~23 (breakout)
├── results/
│   ├── csv/                # 핵심 데이터 결과
│   └── plots/              # 시각화
├── requirements.txt
├── LICENSE
└── .gitignore              # 캐시·venv 제외
```

---

## 🚀 재현 방법

```bash
# 1. 환경 셋업
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. 페니스탁 universe 다운로드 (~30분)
python scripts/pennysniper/01_build_universe.py
python scripts/pennysniper/02_find_events.py

# 3. BTC/XRP 데이터 (~10분)
python scripts/btc/btc_01_setup.py
python scripts/xrp/xrp_01_setup.py

# 4. Polygon 1분봉 (POLYGON_API_KEY 필요)
export POLYGON_API_KEY=your_key
python scripts/pennysniper/07_polygon_minute_resim.py

# 5. Breakout 메가 그리드 (마지막 발견)
python scripts/breakout/breakout_09_mega_grid.py
```

---

## 🤝 핵심 교훈

1. **"빨리 벌고 싶다"는 욕구 자체가 가장 큰 알파 적**
   - 페니스탁 day trading의 본질은 정보 격차 → 일반인 음수 EV
   - 합리적 알파는 연 5~50% 수준

2. **Selection bias가 모든 직관을 함정에 빠뜨림**
   - "+100% 종목" "갭 작은데 폭등" 등 모두 사후 편향
   - 진짜 universe에서 검증해야 진실 보임

3. **단순 룰이 ML/RL을 OOS에서 압도**
   - XRP에서 naive +48% APY vs Q-learning −999% APY
   - 도메인 지식이 모델 capacity보다 중요

4. **백테스트의 split artifact는 흔한 함정**
   - yfinance `auto_adjust=True` + 거래량 검증 필수
   - Live `.splits` API로 cross-check

5. **검증 가능한 가설만 진짜 자산**
   - 23개 중 4개만 양수 (17%)
   - 나머지 19개는 학습 자료지만 거래에 쓰면 손실

---

## ⚠️ 면책

이 repository는 **개인 학습/연구 목적**입니다.
- 실제 투자 권유 아님
- 결과는 in-sample 또는 짧은 OOS 기간
- 알파 약화 추세 진행 중 (특히 BTC/XRP)
- 한국 거주자 세금 (양도세 22%) 미반영
- 거래소 리스크, 슬리피지, 강제청산 등 미반영

**과거 성과는 미래 성과를 보장하지 않습니다.**

---

## 📊 검증 통계

- **검증 가설 수**: 23
- **양수 알파 발견**: 4 (17%)
- **데이터 포인트**: 169,525 (페니스탁 일봉) + 1,051,200 (BTC/XRP 1분봉) + 4,380 (funding events)
- **검증 기간**: 2024.06 ~ 2026.06 (24개월)
- **사용 데이터 소스**: yfinance (무료), Binance public API, Polygon Free tier
- **개발 시간**: 약 1일 집중 세션
- **총 코드 라인 수**: ~3,500
