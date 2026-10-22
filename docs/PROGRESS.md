# KEL 진행 상황 (PROGRESS.md)

세션을 시작할 때 이 파일과 [DECISIONS.md](DECISIONS.md)를 먼저 읽고 이어서 작업한다.
세션을 끝낼 때 갱신한다.

## 단계별 상태

| 단계 | 상태 | 비고 |
|---|---|---|
| Phase 0. 설계 | **완료**: DESIGN.md v0.2, 결정 확정(사용자 위임) | [DESIGN.md](DESIGN.md), [DECISIONS.md](DECISIONS.md) |
| Phase 1. 부트스트랩 | **진행 중**: stage 1 완료·검증, stage 2 빌드 중 | 아래 Phase 1 표 |
| Phase 2. 빌드 시스템과 패키지 관리 | 일부 선행 구현 | `kel` 패키지 빌드·apk 패키징·서명 색인 (단위 테스트로 확인) |
| Phase 3. 첫 부팅 이미지 | 시작 전 | |
| Phase 4. 엔터프라이즈 기능 | 시작 전 | |
| Phase 5. 문서 | 시작 전 | |

### Phase 1 단계별 상태 (x86_64)

| 단계 | 상태 | 결과 |
|---|---|---|
| stage 0 호스트 점검 | 완료 | `./kel check-host` 전부 통과 (Ubuntu 24.04, gawk·texinfo 추가 설치) |
| host-tools | 완료 | apk-tools 3.0.8 (호스트용 패키징 도구) 9초 |
| stage 1 크로스 툴체인 | **완료·검증** | binutils 1m17s, GCC pass 1 13m59s, 헤더 8s, glibc 4m29s, libstdc++ 1m06s (합계 약 21분) |
| stage 2 임시 도구 | 진행 중 | 레시피 17개 (LFS 12.4 6장, 최신 업스트림) |
| stage 3 격리 환경 진입·최종 패키지 | 준비 중 | filesystem 레시피, sysroot 루트 샌드박스, 패키지 빌드 경로 구현 완료. LFS 7·8장 조사 중 |
| stage 4 셀프 호스팅 | 시작 전 | |
| stage 5 재현성 비교 | 시작 전 | |

stage 1 검증 내용: 크로스 GCC로 만든 프로그램이 `/lib64/ld-linux-x86-64.so.2`를 요구하고, KEL sysroot의
crt 파일과 `libc.so.6`에 링크되며, C++ 프로그램이 KEL의 glibc·로더로 실행됨. `.comment`는
`GCC: (GNU) 16.2.0`(호스트 Ubuntu 컴파일러 흔적 없음). GCC pass 1 실측 13m59s는 SBU 추정(3.8 SBU ≈ 13.7분)과 일치.

## 다음에 할 일

1. stage 2 완료와 검증 (sysroot의 도구가 KEL glibc로 실행, 호스트 흔적 없음)
2. stage 3: LFS 7장 임시 도구(gettext, bison, perl, python, texinfo, util-linux)를 sysroot 루트
   샌드박스에서 빌드 → 8장 패키지를 `profile = "package"` 단계로 빌드해 첫 apk 저장소 생성
3. stage 4: stage 3 패키지만으로 만든 빌드 루트에서 전체 재빌드 (KEL의 apk 사용)
4. stage 5: 재빌드 결과 비교 보고서

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

### 2026-10-22 — Phase 1 (같은 세션)

- 사용자가 Phase 0 결정을 위임("다 너가 정해") → D-001~D-017 등 확정, DESIGN.md v0.2.
- `kel` 도구 구현: 레시피 검증, 소스 캐시·서명 검증, bubblewrap 샌드박스(host/sysroot 두 모드),
  부트스트랩 실행기(재개 가능), 패키지 빌드(apk 패키징, `so:` 의존성, 정책 검사, 서명 색인), ELF 리더.
  단위 테스트는 `tools/check`로 실행.
- 레시피: stage 1(binutils, gcc, linux, glibc), stage 2(15개 + binutils/gcc pass 2), filesystem,
  apk-tools(호스트용). 업스트림 공개 키 19개를 `keys/upstream/`에 고정.
- 문제와 해결:
  - `export-minimal`로 키를 내보내면 만료된 부키가 빠져 glibc 서명 검증 실패 → 전체 내보내기.
  - apk는 버전 없는 provides를 자동 선택하지 않음 → `so:` provides에 버전을 붙임.
  - apk는 소유자를 이름으로 기록 → 패키징을 user namespace의 uid 0으로 실행.
  - 레시피 전체 해시로 단계를 판정하면 프로필 추가만으로 재빌드됨 → 프로필별 입력으로 판정.
  - 테스트 실패 상태로 커밋이 한 번 올라감(커밋 명령이 `tail` 뒤에 붙어 있었음) → 바로 수정 커밋,
    이후 `tools/check` 통과 시에만 커밋.
