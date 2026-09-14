# 인트라넷 업무 자동화 도구

사내 인트라넷에 **로그인 → 정해진 순서대로 클릭 → 엑셀 내용 입력**까지를 반복해 주는 도구입니다.
코드를 고칠 필요 없이 **시나리오 파일(YAML) 한 개**만 회사 화면에 맞게 적으면 됩니다.

```
엑셀 (입력 데이터)  ──▶  시나리오 YAML (화면 조작 순서)  ──▶  브라우저 자동 조작
                                                          └─▶ 결과 CSV / 오류 화면 캡처
```

---

## 1. 설치

Windows 라면 `scripts\설치.bat` 을 더블클릭하면 끝입니다. 직접 하려면:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium     # 자동화용 브라우저 1회 설치
```

> 사내망에서 외부 접속이 막혀 있으면 `playwright install` 이 실패합니다.
> 이때는 사내에 이미 깔린 크롬/엣지를 쓰도록 시나리오에 `browser.channel: msedge` 를 적으면 됩니다.

## 2. 첫 실행 (3분)

```bash
# 1) 시나리오와 비밀값 파일을 복사
cp config/scenario.example.yaml config/scenario.yaml
cp config/.env.example config/.env

# 2) config/.env 에 실제 사번/비밀번호를 적는다

# 3) 브라우저를 열지 않고 설정만 점검
python run.py validate

# 4) 동봉된 샘플 엑셀로 실행 계획을 미리 본다 (브라우저 안 열림)
python run.py run --dry-run

# 5) 실제 실행 (처음에는 1건만)
python run.py run --limit 1
```

`pip install -e .` 로 설치했다면 `python run.py` 대신 `intranet-bot` 명령을 써도 됩니다.

## 3. 선택자(selector) 알아내기

가장 막히기 쉬운 부분입니다. 아래 명령을 쓰면 **직접 클릭한 것이 그대로 선택자로 표시**됩니다.

```bash
python run.py record https://intranet.example.co.kr
```

창이 두 개 뜹니다. 왼쪽 브라우저에서 평소처럼 로그인하고 클릭하면,
오른쪽 창에 `#userId`, `button[type=submit]` 같은 선택자가 쌓입니다. 그걸 시나리오에 옮겨 적으면 됩니다.

## 4. 명령어

| 명령 | 하는 일 |
| --- | --- |
| `python run.py validate` | 시나리오 문법 · 비밀값 · 엑셀을 점검만 한다 |
| `python run.py rows` | 엑셀에서 실제로 읽어올 값을 미리 본다 |
| `python run.py run --dry-run` | 브라우저 없이 전체 실행 계획을 출력한다 |
| `python run.py run` | 실제로 자동 입력을 실행한다 |
| `python run.py record <주소>` | 클릭을 기록해 선택자를 알려준다 |

`run` 에서 자주 쓰는 옵션:

| 옵션 | 설명 |
| --- | --- |
| `--limit 1` | 앞에서 1행만 처리 (첫 시험에 권장) |
| `--rows 5-20` 또는 `--rows 3,7` | 특정 엑셀 행만 처리 |
| `--resume` | 지난번에 성공한 행은 건너뛰고 이어서 실행 |
| `--headless` | 창을 띄우지 않고 실행 (익숙해진 뒤에) |
| `--keep-open` | 끝나도 브라우저를 닫지 않음 (원인 확인용) |
| `--log-file 로그.txt` | 로그를 파일로도 남김 |

## 5. 시나리오 파일 구조

`config/scenario.example.yaml` 에 주석과 함께 전체 예시가 들어 있습니다. 큰 틀은 다음과 같습니다.

```yaml
name: "일일 실적 등록"
base_dir: ".."          # 아래 상대경로들이 기준으로 삼을 폴더 (이 파일 위치 기준)

browser:   # 어떤 브라우저로, 어떻게 띄울지
run:       # 오류가 났을 때의 동작, 결과 저장 위치
login:     # 로그인 주소와 순서
excel:     # 어떤 엑셀의 어느 열을 읽을지
flow:
  setup:     [...]   # 로그인 직후 1회
  per_row:   [...]   # 엑셀 행마다 반복  ← 본체
  teardown:  [...]   # 전부 끝난 뒤 1회
```

### 값 채워 넣기 (치환식)

| 쓰는 법 | 의미 |
| --- | --- |
| `{{ row.partner }}` | 엑셀 현재 행의 `partner` 열 값 |
| `{{ secret.INTRANET_PW }}` | `.env` 의 비밀값 (로그에는 `********` 로만 남음) |
| `{{ var.부서 }}` | 시나리오 `vars` 에 적어 둔 고정값 |
| `{{ env.HOME }}` | 환경변수 |
| `{{ now.date }}` | 오늘 날짜 (`now.datetime`, `now.time`, `now.date_compact` 등) |
| `{{ row_index }}` | 지금 처리 중인 엑셀 행 번호 |

엑셀 값은 화면에 넣기 좋은 형태로 자동 변환됩니다.
`1500000.0` → `1500000`, 날짜 셀 → `2026-03-02`, 빈 칸 → 빈 문자열.

### 쓸 수 있는 동작 (action)

| action | 필수 | 선택 | 설명 |
| --- | --- | --- | --- |
| `goto` | `url` | `wait_until` | 주소로 이동 |
| `click` | `selector` | `nth`, `force`, `button` | 클릭 |
| `double_click` | `selector` | `nth`, `force` | 더블클릭 |
| `fill` | `selector`, `value` | `nth` | 칸을 비우고 한 번에 입력 (가장 빠름) |
| `type` | `selector`, `value` | `delay_ms`, `clear_first` | 한 글자씩 입력 (자동 천단위·자동완성 대응) |
| `paste` | `selector`, `value` | `clear_first` | 클립보드로 붙여넣기 (Ctrl+V) |
| `select_option` | `selector` | `option_label`, `value`, `index` | 드롭다운 선택 |
| `check` / `uncheck` | `selector` | `nth` | 체크박스 |
| `press` | `key` | `selector` | 키 입력 (`Enter`, `Tab`, `Control+S` 등) |
| `upload` | `selector`, `path` | | 파일 첨부 |
| `wait_for` | `selector` | `state` | 요소가 나타날 때까지 대기 |
| `wait_for_text` | `text` | `selector` | 특정 문구가 뜰 때까지 대기 |
| `wait_for_url` | `url` | | 주소가 바뀔 때까지 대기 |
| `wait` | `ms` | | 정해진 시간만큼 대기 |
| `switch_frame` | | `selector`, `name`, `url` | iframe 안으로 전환 (인자 없이 쓰면 복귀) |
| `screenshot` | | `path` | 화면 저장 |
| `assert_text` | `text` | `selector` | 문구가 있는지 확인 (없으면 실패 처리) |
| `assert_visible` | `selector` | `nth` | 요소가 보이는지 확인 |
| `handle_dialog` | | `accept`, `prompt_text` | 이후 뜨는 alert/confirm 자동 처리 |

모든 동작에 공통으로 붙일 수 있는 항목:

| 항목 | 설명 |
| --- | --- |
| `label` | 로그에 표시할 설명 (예: `"저장 버튼"`) |
| `timeout_ms` | 이 단계만 대기 시간을 늘리고 싶을 때 |
| `optional: true` | 실패해도 무시하고 진행 (예: 가끔만 뜨는 공지 팝업) |
| `skip_if_empty: "row.note"` | 그 값이 비어 있으면 이 단계를 건너뜀 |

## 6. 안전장치

* **비밀번호는 시나리오에 적지 않습니다.** `config/.env` 에만 두고, 이 파일은 `.gitignore` 로 저장소에서 제외됩니다.
  로그와 화면 출력에서도 비밀값은 `********` 로 가려집니다.
* **`on_error: stop`(기본)** 이면 첫 실패에서 즉시 멈춥니다. 잘못된 데이터가 계속 등록되는 것을 막습니다.
  전부 시도하고 실패분만 나중에 보려면 `continue` 로 바꾸세요.
* **실패하면 증거가 남습니다.** `output/errors/` 에 그 순간의 화면(PNG)과 HTML 이 저장됩니다.
* **이어하기.** 성공한 행은 `output/checkpoint.json` 에 기록되므로, 중간에 멈춰도 `--resume` 으로 이어서 실행하면 중복 등록되지 않습니다.
* **결과 기록.** 실행이 끝나면 `output/result-<날짜시각>.csv` 에 행별 성공/실패가 남습니다 (엑셀에서 바로 열립니다).

## 7. 자주 겪는 문제

| 증상 | 해결 |
| --- | --- |
| `로그인 확인에 실패했습니다` | `.env` 의 아이디/비밀번호, 그리고 `login.success_selector` 가 로그인 후에만 보이는 요소인지 확인 |
| `Timeout ... waiting for locator` | 선택자가 틀렸거나 화면이 느린 경우. `record` 로 선택자를 다시 확인하고, `defaults.timeout_ms` 를 늘려 보세요 |
| 입력은 되는데 저장이 안 됨 | 사내 화면이 `iframe` 을 쓰는 경우가 많습니다. `switch_frame` 을 넣어 보세요 |
| 금액 칸에 값이 이상하게 들어감 | 자동 천단위 스크립트가 있는 칸입니다. `fill` 대신 `type` 을 쓰세요 |
| 인증서 경고로 진입 불가 | `browser.ignore_https_errors: true` (기본값) 확인 |
| `playwright install` 이 사내망에서 실패 | `browser.channel: msedge` 로 사내에 설치된 엣지를 사용 |
| 확인창(alert) 때문에 멈춤 | `flow.setup` 맨 앞에 `handle_dialog` 를 넣으세요 |

## 8. 개발자용

```bash
python -m pytest                          # 전체 테스트 (브라우저 통합 테스트 포함)
python -m pytest --ignore=tests/test_integration.py   # 브라우저 없이 빠르게
```

`tests/fake_intranet/` 에 테스트용 가짜 인트라넷(로그인 + iframe 입력 화면)이 들어 있어,
실제 사내 시스템 없이도 로그인부터 엑셀 입력까지 전체 흐름을 검증합니다.
Playwright 브라우저가 없는 환경에서는 통합 테스트만 자동으로 건너뜁니다.

```
src/intranet_bot/
  cli.py         명령줄 처리
  config.py      시나리오 YAML 읽기·검증 (사용 가능한 action 목록도 여기)
  excel.py       엑셀 읽기
  templating.py  {{ ... }} 치환
  secrets.py     .env 비밀값 처리와 마스킹
  steps.py       action → 실제 브라우저 동작
  runner.py      로그인·행 반복·오류 처리·결과 기록
```

## 9. 사용 시 유의

이 도구는 **본인에게 권한이 있는 사내 시스템에서, 본인이 직접 하던 입력 작업을 대신**하는 용도입니다.
사용 전에 사내 정보보안 정책과 해당 시스템의 이용 규정을 확인하시고,
필요하면 시스템 담당 부서에 자동 입력 사용 가능 여부를 먼저 문의하세요.
