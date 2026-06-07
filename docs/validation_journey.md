# Validation Journey — 23 Hypotheses → 1 Live System

> 처음 PRD v3.0 (페니스탁 RL day-trading)에서 출발해서, 23개 가설을 정밀 검증한 후
> 살아남은 1개 룰을 자동화 시스템으로 만든 전체 여정.

---

## 📖 이 문서의 목적

`README.md`는 **현재 운영 중인 시스템의 사용법**을 다룹니다.
이 문서는 **그 시스템에 도달하기까지의 검증 일지**입니다.

각 가설마다:
- 어떤 가정이었는가
- 어떻게 검증했는가
- 결과 (정직한 숫자)
- 왜 통과/탈락했는가

---

## 🗺️ 전체 여정 (한눈에)

```
Phase 1: 페니스탁 day-trading 검증 (가설 1~15)
   결과: 모두 음수 알파, 데이터 자체에 신호 거의 없음
   ↓
Phase 2: 시장 변경 (가설 16~20)
   BTC funding arb / XRP mean reversion / RL walk-forward
   결과: BTC +5% APY, XRP +48% APY (naive),
         RL은 같은 데이터에서 -999% APY (실패)
   ↓
Phase 3: 페니스탁 재검증 — Breakout 패턴 (가설 21~24)
   "$1 미만에서 머문 후 $1.05~$1.50 첫 돌파" 신호
   결과: 분기별 룰 +1,768%, 월별 룰 +2,749%, 매일 룰 +3,133%
   ↓
Phase 4: 룰을 운영 시스템으로 (Live)
   매일 GH Action이 yfinance에서 데이터 fetch,
   현재 룰로 시그널 탐지, HTML 리포트 자동 생성
```

---

## Phase 1 — 페니스탁 단기 자동매매 (15개 가설)

### H1. 거래량 폭발 후 다음날 매수
- 데이터: 494건 trigger, 274 종목
- 결과: 승률 21.7%, gross **−2.82%/거래**
- 출구 비율: SL 81% / TP 19% (4:1 손실 우세)

### H2. +100% 시점 진입 (1분봉, Polygon)
- 데이터: 100건 (path-resolved)
- 결과: 승률 23%, gross **−1.36%**
- 일봉 추정 +0.38% → 분봉 정밀 −1.36% (1.74%p 악화)

### H3. 18-feature univariate edge
- 방법: t-test + Bonferroni (α=0.05/18=0.0028)
- 결과: **0개 feature 통과**
- 가장 강한 p-value = 0.077

### H4. Logistic OOS classification
- Train 70% / Test 30%
- 결과: 18 trades, 승률 33%, mean +3.24% (작은 N)
- 비용 5%로 −1.76%

### H5. Walk-forward learning curve
- Logistic + Random Forest, expanding window
- 결과: **학습 데이터 늘수록 OOS alpha 감소**
- → capacity 추가는 도움 안 됨

### H6. +30% 빠른 트리거 (clean subset)
- "30분 이내 +30% 도달" 시그널
- Selection bias 통제 후: gross **−5.00%** (clean subset 모두 SL)

### H7. Oracle exit upper bound
- 진입 후 perfect-foresight max exit
- N=6 → 통계적 무의미

### H8~H15
- 시간대별, 거래량 군집, 숏 전략, 펌프앤페이드, 갭 트레이딩, Co-movement, Sector momentum
- **모두 통계적 유의 알파 없음**

**Phase 1 결론**: 페니스탁 1분봉 OHLCV에는 일반인이 잡을 수 있는 신뢰 가능한 알파 없음. 169,525건 full-universe 백테스트로 최종 확인.

---

## Phase 2 — 시장 변경 (가설 16~20)

### H16. BTC Funding Arbitrage
- 방법: BTC spot long + perp short (delta-neutral)
- 데이터: 2,190 funding events (2년)
- 결과: **+5.0% APY** (수수료 차감 후)
- 단점: 알파 약화 중 (2024 +8% → 2026 +1%)

### H17. BTC 1분봉 Mean Reversion
- 1시간 −X% 하락 → N분 hold
- 결과: −3% threshold / 30min hold OOS APY **+3.83%**

### H18. XRP Funding Arbitrage
- 결과: **+3.91% APY**
- BTC와 비슷, 변동성 더 큼

### H19. XRP −7%/1h Mean Reversion (Naive Rule) ⭐
- 단순 룰: 1시간 −7% 하락 → 4시간 hold
- TRUE walk-forward 552일 OOS:
  - 21건, 승률 86%, mean +3.47%, **APY +48.18%**
- per-year 일관: 2024 +4%, 2025 +2.5%, 2026 +3% (모두 양수)

### H20. XRP Q-learning RL Walk-Forward ❌
- 동일 데이터에 tabular Q-learning 적용
- 결과: **6,013건 거래, 승률 32%, APY −999%**
- 동일 OOS 기간 naive 룰 +48% vs RL −999%
- **결론**: RL은 알파 발견 못 함, 거래비용 폭증으로 자본 파괴

---

## Phase 3 — 페니스탁 Breakout (가설 21~24)

### H21. 90d cons + $1.05~$1.20 + TP $2.40
- 90일 종가 < $1, 오늘 close 1.05~1.20, 거래량 ≥ 10K
- N=15 (15 unique 종목)
- 180일 horizon: 13건 완료, 승률 92.3%, mean +81.06%

### H22. 60d cons + $1.05~$1.20 + TP $2.40
- N=25 (22 unique 종목)
- 180일 horizon: N=21, 승률 90.5%, mean +85.34%

### H23. Mega-grid 최적화
- 그리드: cons {30,45,60d} × TP {$1.5,$2,$2.4,$3,$5} × horizon {30,60,90,180d} × alloc {ALL_IN, 25%, 10%}
- 자본 성장 최대: **30d/$3.0/90d ALL_IN** → ₩61.5M (+6,049%)
- 가장 robust: **60d/$3.0/180d** → 승률 91%, p10 +39%

### H23-validation. Selection Bias 검증 (Stooq full universe)
- 4,658개 NASDAQ 종목 + warrant 제외
- 같은 룰 60d/$3.0/180d 재검증:
  - N=21 → **N=51** (universe 7배)
  - 승률 91% → **67%**
  - p10 +39% → **−51%**
- **결론**: 작은 universe에서 과대 추정. Full universe로는 평균 ~+79% (여전히 양수)

### H24. Rolling Walk-Forward (시간 적응형) ⭐⭐⭐
- 정적 룰의 한계 발견 후 적응형으로 전환

#### H24a. 분기별 재학습 (3mo train, 3mo apply)
- 13개 OOS 윈도우 (2023.04 ~ 2026.06)
- 94 OOS 거래, 승률 83%, mean **+13.67%**
- ₩1M with 25% allocation → **₩18.7M (+1,768%)**

#### H24b. 매월 재학습 (3mo train, 1mo apply)
- 38 윈도우, 70 거래
- 승률 87%, mean **+20.61%**
- ₩1M → **₩28.5M (+2,749%)**
- **분기별 대비 +52% 향상** ⭐ (현재 운영 시스템)

#### H24c. 매일 재학습 (60d train, 1d apply)
- 129 윈도우, 69 거래
- 승률 86%, mean **+21.74%**
- ₩1M → **₩32.3M (+3,133%)**
- 월별 대비 +13%, 운영 복잡도 ↑

### H25. 갭업 필터 검증 (TGHL 실패 케이스 동기)
- 가설: "비정상적 큰 갭업"이 실패 원인일 것
- 실제: **승자도 패자도 갭업 분포 비슷** (승자 max +69%, 패자 max +49%)
- 결론: **필터 추가가 오히려 수익 감소**, TGHL은 outlier
- → 필터 추가 안 함 (현재 룰 유지)

---

## Phase 4 — 운영 시스템 구축

`scripts/live/`로 자동화:

1. **fetch_universe.py**: yfinance에서 NASDAQ 페니스탁 일봉 fetch (incremental)
2. **monthly_retrain.py**: 매월 1일 직전 3개월 데이터로 룰 재최적화
3. **daily_report.py**: 현재 룰로 시그널 탐지 → HTML 리포트
4. **GH Action**: 매 평일 자동 실행, GitHub Pages 배포

---

## 🎯 모든 가설 결과 (한 표)

| # | 가설 | 결과 | 살아남음? |
|---|---|---|---|
| 1~13 | 페니스탁 단기 다양 | 모두 음수 (full universe) | ❌ |
| 14, 15 | Co-movement, Sector | ~0 | ❌ |
| 16 | BTC funding arb | +5% APY | ⚠️ 약화 중 |
| 17 | BTC mean rev | +4% APY | ⚠️ |
| 18 | XRP funding arb | +4% APY | ⚠️ 약화 중 |
| **19** | **XRP −7% naive** | **+48% APY** | ✅ |
| 20 | RL walk-forward | −999% APY | ❌ (실패 |
| 21~22 | 페니스탁 정적 룰 | OOS 약화 | ❌ |
| 23 | Mega grid | 큰 수익 가능 | ⚠️ Selection bias |
| 24a | 분기별 재학습 | +1,768% | ⚠️ |
| **24b** | **월별 재학습** | **+2,749%** | ✅ **현재 운영** |
| 24c | 매일 재학습 | +3,133% | ⚠️ 운영 복잡 |
| 25 | 갭업 필터 | 도움 안 됨 | ❌ |

---

## 📚 핵심 교훈 5가지

### 1. Selection bias가 모든 직관을 함정에 빠뜨림
- 작은 universe + 사후적 필터 = 과대 추정
- 진짜 universe (전체 + delisted)에서 검증 필수

### 2. RL은 알파를 발견하지 못함
- 같은 데이터, 같은 OOS:
  - 단순 룰: +48% APY
  - RL: −999% APY
- RL은 신호가 있을 때 활용하는 도구이지 발견하는 도구가 아님

### 3. 시장은 변하므로 룰도 변해야 함
- 정적 룰 OOS: −0.5%
- 적응형 (월별 재학습): +20.6%
- → **현재 시스템의 핵심**

### 4. 단순한 룰이 복잡한 모델을 이김
- 18 features → 0 통과 (Bonferroni)
- ML/RL → OOS 실패
- 단순 breakout 룰 → 성공

### 5. 정직한 negative result가 가장 큰 자산
- 23개 중 18개가 음수
- 그 18개를 안 한 게 진짜 가치
- "왜 안 되는지를 데이터로 아는 것" = 시장 통찰

---

## ⚠️ 정직한 한계

운영 시스템도 다음을 잊지 말 것:

- **In-sample 그리드 search overfitting** 일부 잔존
- **2018-2022 약세장 미검증**
- **슬리피지 2% 가정** (페니스탁 실제 5~10%)
- **한국 거주자 양도세 22% 미반영**
- **시그널 빈도 감소 추세** (시장 효율화)
- **백테스트 ₩28M ≠ 실전 ₩28M**
- **Paper trading 6개월+ 후 실전 권장**

---

## 📁 관련 문서

- [README.md](../README.md) — 현재 운영 시스템 사용법
- [findings.md](findings.md) — 가설별 정밀 결과
- [rolling_adaptive_findings.md](rolling_adaptive_findings.md) — 적응형 walk-forward 상세
- [optimal_rule_2026_watchlist.md](optimal_rule_2026_watchlist.md) — 룰 최적화 과정
- [stooq_full_universe_findings.md](stooq_full_universe_findings.md) — Selection bias 검증
- [2026_signals_watchlist.md](2026_signals_watchlist.md) — 2026 시그널 추적 + Warrant 발견
- [PRD_v3.0.md](PRD_v3.0.md) — 원본 PRD (출발점, archive)
