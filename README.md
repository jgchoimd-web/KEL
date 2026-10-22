# KEL

KEL is a kelp Enterprise linux.

KEL(Kelp Enterprise Linux, os-release `ID=kel`)은 다른 배포판을 베이스로 쓰지 않는
독립 리눅스 배포판이다. 커널, 툴체인, libc부터 모든 것을 업스트림 소스에서 KEL 자체
빌드 도구 `kel`로 빌드하고, 레시피만으로 언제든 처음부터 다시 만들 수 있게 한다.
엔터프라이즈 서버급 안정성(긴 지원 기간, 보안 업데이트, 서명된 패키지, 재현 가능한
빌드)을 지향한다.

> 상태: **Phase 1(부트스트랩) 진행 중.** 아직 설치할 수 있는 결과물은 없다.

## 문서

- [docs/DESIGN.md](docs/DESIGN.md): 설계 (결정 요약은 0장)
- [docs/DECISIONS.md](docs/DECISIONS.md): 결정 기록
- [docs/PROGRESS.md](docs/PROGRESS.md): 진행 상황과 다음 할 일
- [docs/research/](docs/research/): 조사와 측정 기록 (출처 포함)

## 저장소 구조

```
kel                 빌드 도구 실행 파일 (tools/kel의 런처)
tools/kel/          빌드 도구 (Python 표준 라이브러리만 사용)
tools/tests/        단위 테스트
recipes/<이름>/     레시피 (recipe.toml)
bootstrap/          부트스트랩 단계 정의 (stage1.toml ...)
keys/upstream/      업스트림 소스 서명 검증용 공개 키
docs/               문서
```

## 써 보기

부트스트랩 호스트(지금은 Ubuntu 24.04에서 확인)에서:

```sh
./kel check-host            # stage 0: 호스트 요구사항 확인
./kel lint                  # 레시피 검증
./kel fetch                 # 소스 다운로드 + sha256·서명 검증
./kel bootstrap stage1      # stage 1: 크로스 툴체인 (root가 아닌 사용자로 실행)
./kel sbom zlib             # 빌드된 패키지의 SPDX 3.0.1 SBOM (work/<arch>/repo/sbom/)
./kel compare A B           # 두 패키지 저장소 비교 (stage 5 재현성 검사, 다르면 종료 코드 1)
```

- 빌드는 bubblewrap 샌드박스 안에서 네트워크 없이, 호스트를 읽기 전용으로 둔 채 돈다.
- 결과물은 `work/`, 소스 캐시는 `cache/`에 생긴다(둘 다 git에 넣지 않음).
  `KEL_WORKDIR`, `KEL_CACHEDIR`로 위치를 바꿀 수 있다.
- 테스트: `PYTHONPATH=tools python3 -m unittest discover -s tools/tests`

## 라이선스

KEL이 직접 쓴 코드·레시피·문서는 [MIT 라이선스](LICENSE)다(D-016).
레시피가 내려받는 업스트림 소스와 그에 대한 패치는 해당 업스트림의 라이선스를 따른다.
