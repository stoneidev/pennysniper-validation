# Findings — 23 Hypotheses Tested

상세 결과 문서. README는 요약, 이 파일은 각 가설의 정확한 숫자.

---

## Penny Stock Day-Trading (Hypotheses 1–15)

### H1. 거래량 폭발 후 다음날 매수
- **가설**: 거래량 5배 + 당일 +20% 종목을 다음날 시초가 매수, +10% TP / -5% SL, 1일 hold
- **데이터**: 494건 trigger, 274 종목, 2024.07~2026.06
- **결과**: 승률 21.7%, 거래당 gross −2.82%, 1% 비용시 누적 −13.9
- **출구 비율**: SL 81%, TP 19% (4:1 손실 우세)

### H2. +100% 시점 진입 (1분봉)
- **가설**: 시초가 +100% 도달 시 즉시 매수, +10% TP / -5% SL
- **데이터**: 100건 (Polygon 1분봉)
- **결과**: 승률 23%, gross −1.36%, 비용 3% 후 −4.36%
- **path resolution**: 일봉 추정(+0.38%) 대비 path-resolved에서 −1.74%p 악화

### H3. 18-feature univariate edge
- **데이터**: 100건, 18개 pre-entry feature
- **방법**: t-test, Bonferroni 수정 (α = 0.05/18 = 0.0028)
- **결과**: **0개 feature 통과**. 가장 약한 p-value = 0.077 (first_bar_close_vs_open)

### H4. Logistic OOS classification
- **방법**: Train 70/Test 30, top 3 feature로 logistic regression
- **결과**: Test 18 trades, 승률 33%, mean +3.24% (작은 N), 비용 5%로 −1.76%

### H5. Walk-forward learning curve
- **방법**: training 30→95 expanding window, Logistic + Random Forest
- **결과**: 학습 데이터 늘수록 OOS alpha 감소 (slope −0.07%/event for log, −0.04% for RF)
- **결론**: capacity 추가는 도움 안 됨

### H6. +30% 빠른 트리거 (clean subset)
- **가설**: 30분 이내 +30% 도달 시 매수, +10/-5
- **결과 (전체 67건)**: gross +0.16%, 5분 이내(N=9) +1.67%
- **Selection bias check (clean subset, +100% 미도달)**: gross −5.00% (모두 SL)

### H7. Oracle exit upper bound (clean N=6)
- **방법**: 진입 후 perfect-foresight max exit
- **결과**: clean subset 평균 +15.11% (N=6, 통계 무의미)
- **현실 capture**: RL이 oracle의 30% 잡으면 +4.5% (비용 후 break-even)

### H8. 시간대별 (TOD)
- **방법**: 시간 bucket별 +30% 트리거 후 outcome
- **결과**: 모든 bucket 알파 거의 0~약간 음수, 통계적 유의 없음

### H9. 거래량 군집 quintile
- **결과**: Q3 (3.4~5.9x) clean subset N=15에서 +3.83%, 그러나 Q5 (가장 큰 burst)는 −2.35%
- **단조성 없음** = cherry-picking 의심

### H10. Short strategy
- **방법**: +100% 시점 short, -10% cover TP / +5% cover SL
- **결과**: 100건, 승률 40%, gross +0.93%
- **비용 5% (페니스탁 borrow + spread) 차감**: −4.07%

### H11. Pump-and-fade short
- **결과**: 191건 spike day 중 94.2%가 양봉 마감 (close > open)
- **+50% 도달 후 short, 종가 청산**: 평균 **−24%** (반대 방향)

### H12. Gap trading (spike-only sample)
- **데이터**: 188건 spike day
- **결과**: flat gap (+5%/-3%) 평균 +3.81%, 승률 79%

### H13. Gap trading (FULL universe N=169,525) ✓
- **데이터**: 모든 페니스탁 일봉 × 모든 날짜 (selection bias 없음)
- **결과**: 평균 −0.18%, 비용 3% 후 **−3.18%**, Sharpe −16.66
- **결론**: H12의 알파는 selection bias의 결과

### H14. Co-movement 테마 날
- **데이터**: 178,399 trade-day, 5+ stocks 동시 spike = 테마 날
- **결과**: 테마 날 다음날 평균 −0.23%, 비테마 −0.26%, 차이 −0.4%p (노이즈)

### H15. Sector momentum spillover
- **데이터**: 동 178,399건 + sector metadata
- **결과**: 핫 섹터 평균 −0.22%, 콜드 −0.25% (사실상 동일)

---

## Cryptocurrency (Hypotheses 16–20)

### H16. BTC Funding always-on hedge
- **데이터**: 2,190 funding events (8시간마다, 2년)
- **방법**: BTC spot long + perpetual short, funding 누적 수령
- **결과**: 누적 +10.29%, 0.30% setup 후 net +9.94%, **annualized +4.97%**
- **연도별**: 2024 +8.28%, 2025 +5.13%, 2026 +0.99% (효율화)

### H17. BTC 1분봉 mean reversion
- **방법**: 1시간 -X% 하락 시 매수, N분 hold
- **그리드 결과**: thr -3%/30min walk-forward OOS APY +3.83%
- **상위 -5%/-7% threshold N 너무 작음 (9~14건)**

### H18. XRP Funding always-on hedge
- **결과**: 누적 +8.18%, **annualized +3.91%**
- **변동성 더 큼**: rolling 90d min -3.74% (vs BTC -1.58%)
- **연도별**: 2024 +9.48%, 2025 +3.53%, 2026 −1.80%

### H19. XRP −7%/1h mean reversion (naive) ⭐
- **그리드 in-sample**: thr -7% / hold 240min, N=27, mean +3.51%
- **단순 train/test split**: OOS APY +20.4%
- **TRUE walk-forward (월간 재학습)**: 552일 OOS, 21건, 승률 86%, mean +3.47%, **APY +48.18%**
- **per-year 일관**: 2024 +4.05%, 2025 +2.47%, 2026 +3.06% (모두 양수)

### H20. XRP Q-learning RL walk-forward ❌
- **방법**: 월간 재학습 tabular Q-learning, state=(60min ret bucket, position, held bucket)
- **데이터**: 동일 552일 OOS
- **결과**: **6,013 trades, 승률 32%, mean −0.25%, APY −999%**
- **비교**: 동일 기간 naive -7% rule = **+48%**
- **결론**: RL은 알파 발견 못 하고 거래비용 폭증으로 자본 파괴

---

## Penny Stock Breakout Pattern (Hypotheses 21–23)

### H21. 90d cons + $1.05~$1.20 + TP $2.40
- **조건**: 90일 종가 < $1, 오늘 close 1.05~1.20, 거래량 ≥ 10000
- **N=15** (15 unique 종목, 2024.10~2026.03)
- **180d horizon**: 13건 완료, 승률 92.3%, mean +81.06%, p10 +40.75%, p90 +119.41%
- **TP $2.40 도달율**: 30d=53%, 60d=67%, 90d=71%, 180d=77%

### H22. 60d cons + $1.05~$1.20 + TP $2.40
- **N=25** (22 unique 종목)
- **180d horizon**: 21건 완료, 승률 90.5%, mean +85.34%
- **연도별**: 2024 8건, 2025 15건, 2026 2건 (PDSB, STAK)
- **STAK case study (2026)**: $1.105 진입 → 72일 후 $2.40 TP 도달, +115% net
- **DD 위험**: STAK는 진입 후 −56% intraday 가능 (Day 2 에 $0.48)

### H23. Mega grid 최적화 (cons × TP × horizon × allocation) ⭐
- **그리드**: cons {30, 45, 60d} × TP {1.5, 2.0, 2.4, 3.0, 5.0} × horizon {30, 60, 90, 180d} × alloc {ALL_IN, 25%, 10%}

#### Top 5 by capital growth (₩1M from 2025.01.01)

| cons | TP | horizon | alloc | sigs | win% | mean | **final** | total return |
|---|---|---|---|---|---|---|---|---|
| 30d | $3.0 | 90d | ALL_IN | 34 | 73.5% | +81.4% | **₩61,489,186** | **+6,049%** |
| 45d | $3.0 | 90d | ALL_IN | 30 | 73.3% | +85.3% | ₩61,489,186 | +6,049% |
| 30d | $1.5 | 30d | ALL_IN | 36 | 80.6% | +17.6% | ₩38,136,393 | +3,714% |
| 60d | $3.0 | 90d | ALL_IN | 23 | 78.3% | +87.1% | ₩27,141,381 | +2,614% |
| 60d | $1.5 | 30d | ALL_IN | 25 | 84.0% | +20.0% | ₩23,424,841 | +2,243% |

#### Top 5 by mean return per trade (most robust)

| cons | TP | horizon | N | win% | mean | p10 | p90 |
|---|---|---|---|---|---|---|---|
| 30d | $5.0 | 180d | 31 | 77.4% | **+172.93%** | -31.00% | +360.96% |
| 45d | $5.0 | 180d | 27 | 81.5% | +176.77% | -18.88% | +362.69% |
| **60d** | **$5.0** | **180d** | **21** | **81.0%** | **+176.14%** | **-10.80%** | **+360.96%** |
| 45d | $5.0 | 90d | 30 | 73.3% | +117.74% | -36.28% | +323.60% |
| 30d | $5.0 | 90d | 34 | 73.5% | +110.34% | -35.57% | +320.66% |

#### 자본 운용 별 최적 (₩1M)
- **ALL-IN**: 30d/$3.0/90d → ₩61M (+6,049%)
- **25% per trade**: 30d/$3.0/90d → ₩9.4M (+841%)
- **10% per trade**: 30d/$5.0/90d → ₩4.1M (+310%)

#### 권장 룰 (실전 진입 후보)

```
진입 조건:
  - 직전 30일 종가 < $1.0
  - 평균 거래량 ≥ 10,000
  - 오늘 종가 in [$1.05, $1.20)
  - 어제 종가 < $1.05 (첫 돌파)

진입 가격: 다음날 시초가
청산: TP $3.0 도달 시 즉시 OR 90일 후 close
자본 운용: 25% per trade (분산)
```

**기대치 (in-sample)**: 승률 74%, 거래당 +81%, 연 ~25건 시그널
**리스크**: −51% 단일 거래 손실 가능 (QTEX 사례)

---

## Reverse Split Verification

페니스탁 백테스트의 가장 흔한 함정인 액면병합 (reverse split) 오염 검증:

1. **yfinance auto_adjust=True 사용**: 모든 split이 과거 가격에 자동 보정
2. **yfinance .splits accessor 교차 확인**: 25개 돌파 이벤트의 ±60일 split 검사
3. **거래량 비율 검증**: 25건 모두 cons-period 평균 대비 3x 이상 (real catalyst)

**결과**: split artifact 0건. 모든 시그널 진짜 시장 움직임.

---

## 참고 데이터 소스

| 소스 | 용도 | 비용 |
|---|---|---|
| yfinance | 페니스탁 일봉 OHLCV (2년) | 무료 |
| Polygon Free | 페니스탁 1분봉 (분당 5콜 제한) | 무료 |
| Binance public | BTC/XRP 1분봉 + funding rate | 무료 |
| FINRA / SEC | 향후 short interest 검증용 | 무료 |
