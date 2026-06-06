# 📝 제품 요구사항 문서 (PRD) v3.0

## Project PennySniper — 나스닥 페니스탁 동적 AI 트레이딩 시스템

> **문서 버전:** v3.0  
> **최초 작성:** v1.0  
> **최근 업데이트:** v2.0 → v3.0 (2026.06)  
> **주요 변경:** 
> - Rule-based Baseline 추가 (RL 이전 검증 필수)
> - Liquidity / Concentration 리스크 강화
> - KNN Hybrid + Feature Engineering 개선
> - RL Reward & Training 프로토콜 현실화
> - Slippage 모델 + Backtesting Best Practice 대폭 보강
> - Milestones 현실적 연장 및 Phase 0 추가
> - 추가 가드레일, Monitoring, Logging 강화  
> **상태:** 개선된 Baseline 개발 착수 기준점

---

### 1. 제품 개요 (Product Overview)

- **제품명:** 나스닥 페니스탁 동적 AI 트레이딩 시스템 (Project PennySniper)
- **목적:** 나스닥 페니스탁의 극심한 변동성을 활용해 실시간 급등 패턴을 포착하고, **자본 보존을 최우선**으로 당일 매수·당일 청산 규칙을 준수하는 안정적 자동화 AI 매매 엔진 구축.
- **핵심 가치 (v3.0 업데이트):**
  - Rule-based Baseline → RL Progressive Enhancement 전략
  - 고정 종목 없이 거래량 폭발 종목 최대 15~20개 동적 추적 (30개 → 축소)
  - Hybrid KNN 군집 식별 + 단일 RL 에이전트 (Cluster Label State 입력)
  - ATR 기반 동적 손절 + Trailing Stop + 다중 가드레일
  - Cash Account T+2 규칙 완벽 준수 + Liquidity / Concentration 리스크 관리
  - **Capital Preservation First**: MDD < 15%, Daily Loss Limit, Circuit Breaker 필수

---

### 2. 사용자 및 시스템 환경

- **대상 사용자:** 퀀트 투자 및 알고리즘 트레이딩 시스템을 직접 구축·운영하고자 하는 개발자/투자자.
- **운영 환경:**
  - 미국 나스닥 정규장 (한국 시간 기준 밤 10시 30분 ~ 새벽 5시 / 서머타임 적용 시 밤 9시 30분 ~ 새벽 4시).
  - 로컬 개발 PC 또는 Linux 기반 가상 서버 (AWS EC2, Docker 등).

---

### 3. 아키텍처 설계 결정 사항 (ADR)

#### ADR-001: KNN의 역할 — Hybrid 군집 식별기 (v3.0 업데이트)

**결정:**  
KNN은 여전히 군집 식별기로 동작하되, **Offline Clustering + Online Incremental Update** Hybrid 방식으로 변경.

**근거:** Live regime change 대응 및 cluster stability 확보.

**주요 개선:**
- Offline: 과거 데이터로 K-means / HDBSCAN + PCA
- Online: Incremental KNN 또는 Mini-Batch update
- Drift Detection: 매주 Silhouette Score + Stability Metric 모니터링 (Threshold 미달 시 Re-clustering)
- Feature Vector 강화 (A + B + C):

| 카테고리 | 피처 | 비고 |
|----------|------|------|
| A. Technical | Volume surge, Momentum, ATR, RSI, MACD, VWAP dev | 1분봉 |
| B. Meta | Sector, Float, Market Cap | 장전 캐싱 |
| C. External | Short Interest %, Catalyst flag (가능 시) | yfinance / Finviz |

**예상 군집:** Phase 2 EDA 후 최종 확정 (5~7개 가설)

#### ADR-002: RL 에이전트 구조 (v3.0 업데이트)

**결정:** 단일 PPO 에이전트 유지.  
**State 확장:** News sentiment (선택), VIX, QQQ correlation, Cluster stability score 추가.  
**Action Space:** 관망(0) / 매수(1) / 매도(2) 유지. Position sizing은 별도 Risk Manager가 담당.

#### ADR-003: Reward 함수 설계 (v3.0 업데이트)

**기본 구조:**  
`R_total = R_profit + R_trade_penalty + R_atr_penalty + R_risk_adjusted + R_drawdown`

**주요 개선:**
- `R_profit`: `sign * (abs(pnl) ** exponent)` (exponent Optuna)
- `R_risk_adjusted`: Sharpe/Sortino rolling 요소
- `R_drawdown`: MDD > 10% 시 강한 페널티
- Cluster별 ATR penalty + Transaction cost (estimated slippage) 직접 포함
- Optuna 탐색 공간 확대 및 multi-objective optimization (Profit Factor + MDD + Sharpe)

#### ADR-004: Slippage 현실화 모델 (v3.0 대폭 강화)

**개선된 동적 슬리피지 함수:**
```python
def estimate_slippage(...):
    base = Corwin-Schultz approx
    volume_impact = k * (volume / ADV) ** alpha
    volatility_impact = beta * (ATR / price)
    price_level_impact = gamma / close
    regime_multiplier = 1.0 ~ 2.5 (vol quintile)
    return clip(..., 0.01, 0.10)  # 최대 10% 현실화
```

**매수/매도 비대칭 + Panic exit ×1.8**  
**3단계 + Monte Carlo Perturbation 테스트** 필수.

#### ADR-005: Cash Account T+2 관리 (변경 없음 + Edge Case 보강)

- Business day calendar library 사용
- Partial fill, holiday, weekend 처리 로직 추가
- Daily settled_cash preview 기능

**추가 ADR-006: Risk & Guardrail Framework**

- Daily Loss Limit: -5% → All positions close + Trading pause
- Sector Concentration: 동일 섹터 최대 40%
- Max Concurrent Positions: 10~15
- Volatility Circuit Breaker
- Kill Switch (Manual + Auto)

---

### 4. 핵심 기능 요구사항 (Functional Requirements)

#### 4.1 데이터 파이프라인 및 실시간 스캐너
- **[FR-101]** Liquidity Filter 강화: Price $1.0~$10, ADV > $5M, Spread estimate < 5%
- **[FR-102]** Dynamic Swapping: 최대 20종목, Liquidity + Cluster 다양성 고려하여 퇴출
- **[FR-105]** Sector Meta + Short Interest 캐싱

#### 4.2 AI 판단 엔진
- Rule-based Baseline (Volume + Momentum + ATR Stop) 먼저 구현
- KNN + RL은 Baseline 검증 후 Progressive 적용

#### 4.3 브래킷 리스크 가드레일 (강화)
- ATR 손절 (배수 Optuna)
- Trailing Stop (4~6%)
- Time-based exit (holding > 90분 tighter trail)
- **[FR-306]** Daily Loss Limit & Circuit Breaker
- **[FR-307]** Position Sizing: min(5% equity, settled_cash * 0.5, Kelly/Vol targeting)

---

### 5. 시뮬레이션 및 백테스팅 요구사항 (대폭 강화)

- **Backtesting Best Practices:**
  - Walk-forward Optimization
  - Regime-based OOS (Bull / Bear / Meme / High-vol periods)
  - Survivorship bias 제거 (delisted 종목 포함 데이터셋)
  - Realistic delay (500ms~1s) + Partial fill simulation
- **Evaluation Metrics:** 기존 + Calmar, Omega, Slippage Impact Decomposition, Cluster Stability
- **Optuna:** Multi-objective, Time-series CV 적용

---

### 6. 비기능적 요구사항

- **Latency:** End-to-end ≤ 500ms
- **Monitoring:** Prometheus/Grafana 또는 Slack/Discord alerts (Equity curve, Drawdown, Errors, KNN drift)
- **Logging:** 모든 결정 (KNN label, RL action, reason, actual vs est. slippage) SQLite + JSON
- **Fault Tolerance:** Auto-reconnect, State snapshot, Circuit breaker

---

### 7. 데이터 소스 및 비용 계획

| 소스 | 용도 | 비용 | Phase |
|------|------|------|-------|
| Alpaca 무료 | 1분봉 OHLCV, 종목 메타 | 무료 | 1~2 |
| yfinance | 섹터/float 메타 캐싱 | 무료 | 1~3 |
| Finviz | 거래량 급증 스캐닝, 섹터 보조 | 무료 | 1~3 |
| Alpaca 유료 or Polygon.io | 틱 bid-ask, 실시간 고정밀 | 월 ~$29 | 3+ |

---

### 8. 개발 릴리즈 마일스톤 (현실화)

#### **Phase 0: Rule-based Baseline (1~2주) — 필수**
- Liquidity Scanner + Simple Momentum + ATR Stop 전략
- Backtester + Slippage 3단계 테스트
- Paper trading 1주

#### **Phase 1: 인프라 및 파이프라인 (2~3주)**
- Alpaca SDK, Dynamic Subscription, CashAccountManager, Logging

#### **Phase 2: AI 엔진 및 학습 (4~7주)**
- EDA → KNN Hybrid
- Gymnasium Env (T+2, Slippage, Guards)
- PPO 초기 학습 + Optuna

#### **Phase 3: 통합 및 검증 (6~10주)**
- Full Guardrail + Robustness tests
- Paper trading 최소 6~8주 + Actual slippage logging

#### **Phase 4: Live Small Capital (최소 8주 monitoring)**
- $5k~10k 소액 실전 → Scale or Stop

---

### 9. 미결 결정 사항 (Open Questions)

| 항목 | 상태 | 결정 시점 |
|------|------|-----------|
| 실제 군집 수 | EDA 후 | Phase 2 초 |
| KNN Online Update 방법 | Hybrid 후보 검토 | Phase 2 |
| Reward multi-objective weight | Optuna | Phase 2 |
| Daily Loss Limit & Circuit Breaker threshold | 백테스트 후 | Phase 2 |
| Baseline vs RL 성과 비교 기준 | Profit Factor >1.8, MDD<15%, Sharpe>1.2 | Phase 3 |

---

**v3.0 업데이트 요약**  
이 버전은 **과도한 낙관을 제거**하고, **Rule-based Baseline → RL Progressive** 접근, **리스크 관리 대폭 강화**, **백테스트 현실성 제고**, **개발 기간 현실화**를 핵심으로 반영했습니다.

**개발 원칙:**  
**"Backtest에서 빛나고 Live에서 죽는 전략"을 피한다.** Capital Preservation > Profit Maximization.

---

*이 문서는 개발 진행에 따라 지속 업데이트됩니다. Phase 완료 시 Open Questions를 확정하고 버전을 갱신하세요.*