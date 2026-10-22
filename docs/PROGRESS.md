# KEL 진행 상황 (PROGRESS.md)

세션을 시작할 때 이 파일과 [DECISIONS.md](DECISIONS.md)를 먼저 읽고 이어서 작업한다.
세션을 끝낼 때 갱신한다.

## 단계별 상태

| 단계 | 상태 | 비고 |
|---|---|---|
| Phase 0. 설계 | **완료**: DESIGN.md v0.2, 결정 확정(사용자 위임) | [DESIGN.md](DESIGN.md), [DECISIONS.md](DECISIONS.md) |
| Phase 1. 부트스트랩 | **진행 중** | `kel` 도구 뼈대, stage 1 크로스 툴체인부터 |
| Phase 2. 빌드 시스템과 패키지 관리 | 시작 전 | |
| Phase 3. 첫 부팅 이미지 | 시작 전 | |
| Phase 4. 엔터프라이즈 기능 | 시작 전 | |
| Phase 5. 문서 | 시작 전 | |

## 다음에 할 일

1. Phase 1 stage 1:
   - `tools/kel` 뼈대: 레시피 로더(TOML), 소스 가져오기와 sha256·서명 검증, bubblewrap 실행기
   - 크로스 툴체인 레시피: binutils → GCC pass 1 → Linux API headers → glibc → libstdc++
   - 첫 검증: `x86_64-kel-linux-gnu-gcc`로 만든 hello world가 KEL sysroot의 glibc 동적 링커를
     요구하는지 `readelf -l`로 확인
2. Phase 1 stage 2~5: 크로스 임시 도구 → 격리 환경 진입 → 패키지 빌드 → 셀프 호스팅 → 재현성 비교

## 세션 기록

### 2026-10-22 — Phase 0

- 작업 환경 확인: 4 vCPU, 15 GiB RAM, 디스크 여유 약 31 GB, KVM 없음, user namespace 사용 가능.
  자세한 값은 [research/2026-10-22-environment.md](research/2026-10-22-environment.md).
- 빌드 처리량: 1 SBU(LFS 정의, 코어 1개) = 216.9초, `-j4` = 82.5초 (binutils 2.47 크로스 빌드로 측정).
- QEMU TCG 부팅 시간: x86_64 UEFI 8.6초, aarch64 UEFI 16.3초 (측정용 커널 + busybox).
- bubblewrap: 일반 사용자 권한으로 네트워크 차단 샌드박스 동작 확인.
- 업스트림 tarball 서명 검증(binutils 2.47, GCC 16.2.0, glibc 2.44). glibc 서명 키는 GNU keyring 사본에서
  만료로 표시됨 → 레시피에 키 지문을 고정하는 방식으로 설계.
- 업스트림 조사(출처 포함): [research/2026-10-22-upstream-survey.md](research/2026-10-22-upstream-survey.md).
- apk-tools 3.0.8 사전 검증: 4.5초 빌드, 서명된 패키지·색인으로 설치/업그레이드/삭제, 신뢰하지 않는 키·변조
  패키지 거부, 서명 전 패키지 재현성 확인. [research/2026-10-22-apk-v3-poc.md](research/2026-10-22-apk-v3-poc.md).
- DESIGN.md 초안 v0.1과 DECISIONS.md(D-000 확정, D-001~D-017 확인 대기, D-018~D-024 보류) 작성.
- 저장소에 비밀 정보가 실수로 들어가지 않도록 `.gitignore`에 개인 키 패턴을 추가.
- 작업 브랜치 `ccr-9b91e992-p0h5sc`, draft PR #1.
