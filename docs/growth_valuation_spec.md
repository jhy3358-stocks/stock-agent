# 성장주 적정가(FV) 모듈 구현 명세 — jhy3358-stock

## 0. Claude Code에 붙여넣을 프롬프트

```
이 저장소(jhy3358-stock)에 docs/growth_valuation_spec.md 명세대로
중소형 성장주 적정가 모듈을 추가해줘.

- 기존 GRAV 수식과 리포트 구조는 건드리지 말고, 새 모듈을 추가하는 최소 변경으로 진행
- 먼저 명세를 읽고 구현 계획(수정/추가 파일 목록)을 보여준 뒤 승인받고 진행
- 7장 테스트 케이스를 pytest로 작성해서 통과시킬 것
- 가정값은 코드에 하드코딩하지 말고 config/growth_assumptions.yaml에서 읽을 것
```

---

## 1. 목표와 적용 범위

- 기존 **GRAV**: Forward EPS가 양수인 대형주(M7 + Broadcom 등)에 그대로 사용. 변경 없음.
- 신규 **Growth FV 모듈**: Forward EPS가 없거나 음수인 성장주, 신규 상장주에 사용.
- 출력은 두 가지: **적정가(FV)** 와 **역산 필요조건**(현재가를 정당화하려면 무엇이 필요한가). 리포트에서는 역산 필요조건을 우선 표시.

### 라우팅
```
if forward_eps > 0 and ticker in GRAV_UNIVERSE: GRAV
else: Growth FV 모듈 (아래 단계 분류)
```

---

## 2. 공통 골격

```
FV = [ EV_n × P / (1+r)^n  +  (1−P) × L / (1+r)^n  +  NetCash_adj ] / S_D,n
```

| 기호 | 의미 |
|---|---|
| EV_n | n년 뒤 기업가치 (단계별 모듈로 계산) |
| P | 사업 성공 확률 (0~1, 고유 위험) |
| r | 할인율 (CAPM, 전 단계 공통, 체계적 위험) |
| n | 평가 기간 (3.2 규칙) |
| L | 실패 시 T 시점 회수가치 (주로 3단계, 나머지는 0) |
| NetCash_adj | 현금 − 부채 − n년 누적 현금소진. 1단계는 음수 허용(부채 조달), 2·3단계는 0 하한(부족분은 증자로 처리) |
| S_D,n | n년 뒤 희석주식수 |

**원칙:** 할인 분모, 현금소진 기간, 주식수 시점은 모두 같은 n으로 맞춘다. 증자 할인은 r이 아니라 S_D,n에만 반영한다(이중 반영 금지).

---

## 3. 공통 파라미터 규칙

### 3.1 할인율 r (전 단계 공통)
```
r = max(rf + β × ERP, 0.12)
rf  = 미국 10년물 금리 (yfinance ^TNX / 100)
ERP = 0.05 (config)
β   = yfinance beta. 없거나 상장 1년 미만이면 config의 peer_beta 사용
```

### 3.2 평가 기간 n
성장률이 15%로 둔화되는 연수로 결정한다.
```
g_1 = min(g0, g_cap)          # g0: TTM 매출성장률, g_cap = 1.0
g_{t+1} = g_t × decay         # decay = 0.75
n = g_t ≤ 0.15 가 되는 최소 t, clamp(n, 5, 10)
3단계는 하한 8 (clamp(n, 8, 10))
```
미래 매출: `R_n = R_0 × Π_{t=1..n} (1 + g_t)`
config에서 `n_override`, `R_n_override`로 덮어쓸 수 있어야 함.

### 3.3 희석주식수 S_D,n
```
S_base    = 현재 희석주식수 × (1 + sbc_rate)^n                  # sbc_rate 기본 0.04
shortfall = max(누적소진 − (현금 − 부채), 0)                    # 2·3단계만
issue_px  = min(현재가, FV_prev) × (1 − issue_discount)          # issue_discount 기본 0.20
S_D,n     = S_base + shortfall / issue_px + 인수합병 신주(config)
```
FV_prev: 처음에는 현재가로 계산한 뒤, 산출된 FV로 1~2회 반복 계산(수렴 시 종료).

### 3.4 누적 현금소진
```
FCF_TTM < 0 이면: burn = |FCF_TTM| × burn_years   # burn_years: config, 기본 min(n, 5)
그 외: burn = 0
1단계는 config의 net_cash_n(애널리스트 전망 순현금) 우선 사용
```

---

## 4. 단계 분류

### 4.1 기준
```
1단계: TTM EBITDA 마진 > +5%
2단계: 1단계가 아니고, 아래 조건을 모두 충족
       - TTM 매출 ≥ $60M
       - 최근 4개 분기 중 3개 이상에서 분기 매출 ≥ $10M
       - TTM 매출성장률 > 0
       - 매출총이익률 > 0
3단계: 위 두 경우가 아닌 전부 (2단계 보조조건 탈락 시 매출 규모와 무관하게 3단계)
```

### 4.2 경계 보간 (주당 FV 기준으로 섞을 것, EV를 섞으면 안 됨)
```
[1↔2] EBITDA 마진 m ∈ [−5%, +5%]:
      FV = FV_2 × (0.05 − m)/0.10 + FV_1 × (m + 0.05)/0.10

[2↔3] TTM 매출 R ∈ [$40M, $60M] 이고 2단계 보조조건 통과 시:
      FV = FV_3 × (60 − R)/20 + FV_2 × (R − 40)/20    (단위: $M)
```

---

## 5. 단계별 EV_n 모듈

### 5.1 1단계 — EBITDA 흑자 (예: SPCX)
사업부별 SOTP:
```
EV_n = Σ_i ( R_n,i × EBITDA마진_i × M_EV/EBITDA,i )
```
- capex / 매출 > 30% 이면 `EBITDA마진_i` 대신 `(EBITDA − capex)마진_i` 사용
- 사업부 정보가 없으면 단일 사업부로 처리
- 기본값: P = 0.9, L = 0

### 5.2 2단계 — 매출 있음, 이익 없음 (예: IONQ)
```
EV_n = Σ_i ( R_n,i × M_EV/S,성숙기,i × GM_i / GM_peer,i )
```
- 성격이 다른 매출(예: 양자 vs 파운드리)은 분리해서 각각 적용
- 기본값: P = 0.6, L = 0

### 5.3 3단계 — 매출 미미, 성장성 (예: RGTI)
```
EV_T = TAM_T × 점유율 × 영업이익률 × (1 − 세율) × P/E_성숙기
```
- 세율 기본 0.21
- 기본값: P = 0.3, L = config (기본 0)

---

## 6. 역산 필요조건 (리포트 핵심 출력)

현재가를 FV 자리에 넣고 EV_n을 역산한다.
```
EV_req = [ (현재가 × S_D,n − NetCash_adj) × (1+r)^n − (1−P) × L ] / P
```
단계별 변환:
- 1단계: `EBITDA_req = EV_req / 가중평균 M_EV/EBITDA` → 필요 매출 = EBITDA_req / 가중평균 마진
- 2단계: `R_req = EV_req / (M_EV/S × GM비율)` → 현재 매출 대비 배수, 필요 CAGR
- 3단계: `점유율_req = EV_req / (TAM_T × 영업이익률 × (1−세율) × P/E)`

리포트 문구 예:
```
IONQ  적정가 $8 / 현재가 $37.5
      현재가 정당화 조건: 2031년 양자 매출 $9.3B (현재의 약 33배, CAGR 약 100%)
RGTI  적정가 $1.2 / 현재가 $16
      현재가 정당화 조건: 2036년 양자 시장 점유율 44%
```

---

## 7. RSI 50 평균가 (최근 126거래일)

### 7.1 전제
- Wilder RSI(14), `ewm(alpha=1/14, adjust=False)` 로 고정
- 수정종가 사용
- 계산 구간 앞에 워밍업 데이터 100거래일 이상 추가로 받기
- 데이터가 126 + 100일 미만이면 가능한 기간으로 계산하고 `data_insufficient=True` 플래그 표시 (예: SPCX는 2026-06-12 상장)

### 7.2 방법 A — 교차점 평균
```
RSI가 50을 통과한 날 t에 대해 선형보간:
P_cross = C_{t−1} + (C_t − C_{t−1}) × (50 − RSI_{t−1}) / (RSI_t − RSI_{t−1})
avg_cross = mean(P_cross)   # 표본 수도 함께 출력
```

### 7.3 방법 B — 역산 RSI50 가격 평균
```
P50_t = C_t + 13 × (AL_t − AG_t)    # 다음 날 RSI가 정확히 50이 되는 종가
avg_p50 = mean(P50_t over 126일)
```

### 7.4 참고 구현
```python
d = close.diff()
ag = d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
al = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
rsi = 100 - 100 / (1 + ag / al)
p50 = close + 13 * (al - ag)
w = rsi.index[-126:]; r0 = rsi.shift(1); c0 = close.shift(1)
x = [t for t in w if (rsi[t] - 50) * (r0[t] - 50) < 0]
p_cross = c0[x] + (close[x] - c0[x]) * (50 - r0[x]) / (rsi[x] - r0[x])
avg_cross, avg_p50 = p_cross.mean(), p50[w].mean()
```

---

## 8. config/growth_assumptions.yaml 예시

```yaml
defaults:
  erp: 0.05
  r_floor: 0.12
  g_cap: 1.0
  decay: 0.75
  sbc_rate: 0.04
  issue_discount: 0.20
  tax: 0.21

SPCX:
  peer_beta: 1.2            # 상장 1년 미만
  P: 0.9
  n_override: 5
  R_n_override: 150000      # $M, 2031
  net_cash_n: -3300         # $M, 애널리스트 전망
  ma_new_shares: 400        # M주, Cursor 인수 가정
  segments:
    - {name: connectivity, share: 0.40, ebitda_margin: 0.60, multiple: 12}
    - {name: ai,           share: 0.50, ebitda_margin: 0.35, multiple: 10}
    - {name: space,        share: 0.10, ebitda_margin: 0.25, multiple: 15}

IONQ:
  peer_beta: 1.8
  P: 0.6
  n_override: 5
  burn_total: 1500          # $M
  segments:
    - {name: quantum, R_n: 1600, ev_s: 7, gm_ratio: 0.9}
    - {name: foundry, R_n: 500,  ev_s: 2, gm_ratio: 1.0}

RGTI:
  P: 0.3
  n_override: 10
  tam_T: 50000              # $M, 2036 양자컴퓨팅 시장 가정
  market_share: 0.03
  op_margin: 0.25
  pe_mature: 25
  L: 200                    # $M, T 시점 IP 매각가치 가정
  burn_total: 1400          # $M
```

---

## 9. 테스트 케이스 (pytest)

8장 config 값(override 포함)으로 계산했을 때 아래 범위에 들어와야 한다. 입력 시장 데이터는 fixture로 고정.

| 티커 | 단계 | 고정 입력 | 기대 FV | 허용 범위 |
|---|---|---|---|---|
| SPCX | 1 | 현재가 149, 주식수 13,500M, r 0.11 | 약 $25 | $22~28 |
| IONQ | 2 | 현재가 37.5, 주식수 400M, 순현금 2,000M, r 0.14 | 약 $8 | $7~9 |
| RGTI | 3 | 현재가 16, 주식수 312M, 순현금 541M, r 0.145 | 약 $1.2 | $1.0~1.4 |

추가 테스트:
- 단계 분류: SPCX→1, IONQ→2(TTM 매출 약 $247M, 분기 4개 모두 ≥ $10M), RGTI→3(TTM 약 $10M)
- 보간 연속성: 매출 $40M, $60M 경계와 EBITDA 마진 ±5% 경계에서 FV가 끊기지 않을 것
- 보조조건 탈락: TTM 매출 $80M이지만 분기 1개만 $10M 이상인 가상 기업 → 3단계
- 역산 일관성: 역산한 EV_req를 다시 넣으면 FV = 현재가 (오차 1% 이내)
- RSI: 상승만 있는 시계열에서 교차점 0개일 때 NaN 처리, P50 계산식 검증(P50을 다음 날 종가로 넣으면 RSI = 50 ± 0.01)

---

## 10. 주의사항

- 모든 가정값(P, 멀티플, TAM, 점유율)은 결과를 2~3배 흔든다. 리포트에 "가정 기반 추정" 문구를 고정 표기.
- FV는 매수/매도 신호로 쓰지 말고, 역산 필요조건과 RSI50 평균가를 함께 참고 지표로 표시.
- yfinance 데이터 누락(beta, FCF, 분기 매출) 시 config 값으로 대체하고 리포트에 대체 사실 표시.
