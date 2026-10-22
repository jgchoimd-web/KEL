# KEL 진행 상황 (PROGRESS.md)

세션을 시작할 때 이 파일과 [DECISIONS.md](DECISIONS.md)를 먼저 읽고 이어서 작업한다.
세션을 끝낼 때 갱신한다.

## 단계별 상태

| 단계 | 상태 | 비고 |
|---|---|---|
| Phase 0. 설계 | **진행 중**: 환경 확인·업스트림 조사 완료, DESIGN.md 작성 중 | [DESIGN.md](DESIGN.md) |
| Phase 1. 부트스트랩 | 시작 전 | Phase 0 결정 확정 후 |
| Phase 2. 빌드 시스템과 패키지 관리 | 시작 전 | |
| Phase 3. 첫 부팅 이미지 | 시작 전 | |
| Phase 4. 엔터프라이즈 기능 | 시작 전 | |
| Phase 5. 문서 | 시작 전 | |

## 다음에 할 일

1. 사용자가 [DECISIONS.md](DECISIONS.md)의 "확인 대기" 항목을 확정하거나 수정한다.
2. 확정되면 DESIGN.md 상태를 v0.2로 올리고 Phase 1을 시작한다.
   - `tools/kel` 뼈대 (레시피 로더, 소스 가져오기와 검증)
   - 크로스 툴체인 레시피: binutils → GCC pass 1 → Linux API headers → glibc → libstdc++
   - 첫 검증: `x86_64-kel-linux-gnu-gcc`로 만든 hello world가 KEL sysroot의 glibc에 링크되는지 확인

## 세션 기록

### 2026-10-22 — Phase 0 시작

- 작업 환경 확인: 4 vCPU, 15 GiB RAM, 디스크 여유 약 31 GB, KVM 없음, user namespace 사용 가능.
  자세한 값은 [research/2026-10-22-environment.md](research/2026-10-22-environment.md).
- 빌드 처리량: 1 SBU(LFS 정의, 코어 1개) = 216.9초, `-j4` = 82.5초 (binutils 2.47 크로스 빌드로 측정).
- QEMU TCG 부팅 시간: x86_64 UEFI 8.6초, aarch64 UEFI 16.3초 (측정용 커널 + busybox).
- 업스트림 조사(출처 포함): [research/2026-10-22-upstream-survey.md](research/2026-10-22-upstream-survey.md).
- 저장소에 비밀 정보가 실수로 들어가지 않도록 `.gitignore`에 개인 키 패턴을 추가.
- (작성 중) DESIGN.md 초안 v0.1, 결정 항목은 DECISIONS.md에 "확인 대기"로 기록 예정.
