# Market News Radar 0.1.4

뉴스 흐름과 ETF·변동성 신호를 함께 해석하는 ChatGPT/Codex 스킬입니다.
이번 릴리즈는 ChatGPT에서 다운로드한 `market-news-radar` 0.1.4의 파일을 그대로 반영합니다.

GitHub 릴리즈의 `market-news-radar-v0.1.4.zip`을 설치하세요. ZIP은 클라우드에서
다운로드한 원본이며, 로컬 설치본과 저장소의 해당 파일 내용도 동일합니다.
전체 실행 지침은 [SKILL.md](SKILL.md), 수집 계약은
[references/source-contracts.md](references/source-contracts.md)에 있습니다.

## 이번 버전

- FinancialJuice, Walter Bloomberg, First Squawk와 기존 세 출판사 피드를 XML로 수집합니다.
- XML 피드와 Trump RSS에 curl을 사용하고, VIX에는 기존 CSV 경로를 사용합니다.
- First Squawk의 시간만 540분 보정하며 원본 시간을 보존합니다.
- 제목·날짜가 없는 항목을 구분하고, 한 소스의 실패가 다른 성공을 지우지 않습니다.
- 한 실행의 수집 결과와 실패를 재사용하며 즉시 재시도하지 않습니다.
- 기존 Alpaca → Alpaca Paper Trading 읽기 전용 대안을 유지합니다.

Python 표준 라이브러리와 curl을 사용합니다. 커넥터 설치·인증은 스킬 설치와 별개입니다.
증권사 주문, 계정 변경과 자동매매는 이 스킬의 범위에 포함되지 않습니다.

## 검증

```sh
python3 -B -m unittest discover -s tests -v
```

클라우드 패키지의 41개 테스트가 통과했습니다. 파싱, 시간 보정, HTTPS 리디렉션,
응답 크기 제한과 소스별 실패 격리를 검사합니다. 이 결과는 실제 피드의 계속된
접근 가능성이나 커넥터 실시간 실행 성공을 보장하지 않습니다.
