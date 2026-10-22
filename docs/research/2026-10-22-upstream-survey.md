# 업스트림 조사 기록 (2026-10-22)

DESIGN.md 추천안의 근거가 되는 사실을 출처와 함께 남긴다. 모든 항목은
2026-10-22에 출처 페이지를 실제로 열어 확인한 것이다.

- **추정**: 공개된 일정이나 지금까지의 패턴으로 계산한 값
- **미확인**: 확인하지 못한 값

버전과 일정은 빨리 바뀐다. 레시피를 만들 때는 이 문서를 그대로 믿지 말고
다시 확인한다.

---

## 1. 커널과 핵심 툴체인

### 1.1 Linux 커널 (GPL-2.0 WITH Linux-syscall-note)

| 항목 | 값 |
|---|---|
| 메인라인 | **7.3** (2026-10-18) |
| 최신 stable | 7.2.12 (2026-10-21) |
| 주기 | 메인라인 9~10주마다, stable은 대략 매주 |
| 7.x 전환 | 6.19(2026-02)가 마지막 6.x, **7.0 = 2026-04-12**. Torvalds: 큰 기능 변화가 아니라 숫자 관리 차원이며 앞으로 대략 3.5년마다 메이저 번호를 올린다 |

**LTS** (kernel.org 표, 2026-02-25 갱신. 새 LTS는 처음에 2년 EOL로 시작하고 날짜는 바뀔 수 있다)

| LTS | 출시 | 예상 EOL | 최신(10월) |
|---|---|---|---|
| 6.18 | 2025-11-30 | 2028-12 | 6.18.58 |
| 6.12 | 2024-11-17 | 2028-12 | 6.12.114 |
| 6.6 | 2023-10-29 | 2027-12 | 6.6.160 |
| 6.1 | 2022-12-11 | 2027-12 | 6.1.190 |
| 5.15 | 2021-10-31 | 2026-12 | 5.15.223 |
| 5.10 | 2020-12-13 | 2026-12 | 5.10.272 |

- 2026년 LTS는 아직 지정 전이다. 5.10 이후 LTS는 모두 그해 마지막 메인라인이었고,
  kernel.org 캘린더의 7.4 출시 예상일이 2026-12-20이다 → **추정: 7.4가 2026 LTS**.
- **CIP SLTS** (최소 10년 목표, 회원사 설정·일부 아키텍처 중심):
  4.4→2027, 4.19→2029, 5.10→2031, 6.1→2033, **6.12→2035년 중반**.
- 커널 최소 툴체인 (`Documentation/process/changes.rst`, master):
  GCC 8.1, binutils 2.30, make 4.0, bash 4.2, bison 2.0, flex 2.5.35,
  Python 3.9, OpenSSL 1.0.0, tar 1.28, bc 1.06.95, kmod 13.
  선택: Clang/LLVM 17.0.1, Rust 1.85.0, bindgen 0.71.1.

출처: <https://www.kernel.org/releases.json>, <https://www.kernel.org/category/releases.html>,
<https://lwn.net/Articles/1059772/>, <https://www.kernel.org/releases-calendar.ics>,
<https://cip-project.org/blog/2026/08/06/a-decade-of-stability-10-years-of-the-cip-kernel-wg>,
<https://cip-project.org/blog/2025/05/26/cip-is-now-supporting-five-slts-kernels>,
<https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/Documentation/process/changes.rst>

### 1.2 GCC (GPL-3.0-or-later, 런타임은 GCC Runtime Library Exception 3.1)

| 브랜치 | 최신 | 날짜 | 상태 |
|---|---|---|---|
| 16 | 16.2 | 2026-08-07 (16.1: 2026-04-30) | 유지 |
| 15 | 15.3 | 2026-06-12 | 유지 |
| 14 | 14.4 | 2026-06-26 | 유지 |
| 13 | 13.5 | 2026-09-11 | **종료** |

- 매년 4~5월 새 메이저(x.1), 이후 대략 연 1회 포인트 릴리스, 가장 오래된 브랜치는
  x.5로 닫힌다 → **브랜치 수명 약 3.5년**. (추정: 16 브랜치는 2029년경까지)
- GCC 15부터 C 기본값 `-std=gnu23`, GCC 16부터 C++ 기본값 `-std=gnu++20`
  → 오래된 패키지에서 빌드 오류가 생길 수 있다.
- GCC 15 이상 빌드에는 C++14 호스트 컴파일러(GCC 5.4+) 필요.

출처: <https://gcc.gnu.org/releases.html>, <https://gcc.gnu.org/pipermail/gcc-announce/2026/000194.html>,
<https://gcc.gnu.org/gcc-15/changes.html>, <https://gcc.gnu.org/gcc-16/changes.html>,
<https://gcc.gnu.org/install/prerequisites.html>

### 1.3 binutils (GPL-3.0-or-later)

- 최신 **2.47** (2026-07-26). 연 2회(1~2월, 7~8월) + 가끔 .1.
- **gold 링커는 2.44부터 deprecated**, 2.45/2.47 tarball에는 없다 → ld.bfd 또는 lld 사용.
- 릴리스 tarball 자체가 재현 가능하게 만들어진다.

출처: <https://sourceware.org/pipermail/binutils/2026-July/150449.html>,
<https://sourceware.org/pipermail/binutils/2025-February/139195.html>, <https://ftp.gnu.org/gnu/binutils/>

### 1.4 glibc (LGPL-2.1-or-later)

- 최신 **2.44** (2026-07-25 발표). 6개월 주기(2월 1일, 8월 1일 무렵), 2.45는 2027-02-01 예정.
- release/2.32 ~ release/2.44 브랜치가 모두 유지 중. master의 ABI/API 무변경 수정은
  백포트 대상. 고정 EOL은 없다.
- **포인트 릴리스 tarball이 없다.** 배포판은 `release/*` 브랜치를 추적하라고 공지한다
  → KEL 레시피는 "릴리스 tarball + release 브랜치 백포트 패치" 또는 "브랜치 커밋 고정"으로 가야 한다.
- 최소 커널: x86_64 3.2.0, aarch64 3.7.0.
- 빌드 요구: GCC 12.1+, binutils 2.39+, make 4.0, Python 3.4, bison 2.7, gawk 3.1.2, texinfo 4.7.
- 2.43부터 Clang 18+ 빌드가 실험적으로 지원(aarch64/x86_64만).

출처: <https://sourceware.org/pipermail/libc-announce/2026/000058.html>,
<https://sourceware.org/glibc/wiki/Release>,
<https://sourceware.org/git/?p=glibc.git;a=blob_plain;f=INSTALL;hb=refs/tags/glibc-2.44>

### 1.5 musl (MIT)

- 최신 **1.2.6** (2026-03-20), 그 전은 1.2.5 (2024-02-29). 릴리스 주기가 불규칙하다.
- 홈페이지에 1.2.6까지 영향을 주는 CVE 3건이 패치로만 제공된다고 적혀 있다.

출처: <https://musl.libc.org/releases.html>, <https://musl.libc.org/>

### 1.6 LLVM/Clang/lld (Apache-2.0 WITH LLVM-exception)

- 최신 **23.1.4** (2026-10-20). 메이저 약 6개월 주기, 각 라인은 .0 이후 약 4개월만 수정. **LTS 없음.**
- 하위 프로젝트별 tarball은 없어졌고 monorepo tarball만 제공.

출처: <https://releases.llvm.org/>, <https://llvm.org/>, <https://llvm.org/docs/HowToReleaseLLVM.html>

### 1.7 Rust (MIT OR Apache-2.0)

- 최신 stable **1.99.1** (2026-10-15). 6주 주기, **LTS 없음**.
- rustc는 직전 버전 컴파일러로 빌드된다. mrustc는 1.90.0까지 바이너리 없이 부트스트랩
  가능(x86_64 Linux만 검증) → 바이너리 없이 가려면 mrustc → 1.90 → … → 최신, 약 9단계.

출처: <https://static.rust-lang.org/dist/channel-rust-stable.toml>,
<https://blog.rust-lang.org/2026/10/15/Rust-1.99.1/>, <https://github.com/thepowersgang/mrustc>,
<https://rustc-dev-guide.rust-lang.org/building/bootstrapping/what-bootstrapping-does.html>

### 1.8 다른 배포판의 하드웨어 기준선

| 배포판 | x86-64 | aarch64 |
|---|---|---|
| RHEL 10 | x86-64-v3 | ARMv8.0-A |
| AlmaLinux 10 | v3 기본 + 별도 x86_64_v2 빌드 | — |
| SLES 16.0 | x86-64-v2 | Armv8.0-A |
| Amazon Linux 2023 | x86-64-v2 | armv8.2-a+crypto |
| Ubuntu 26.04 LTS | amd64 기본 + 선택형 amd64v3 변형 | — |

출처: <https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html/10.2_release_notes/architectures>,
<https://wiki.almalinux.org/release-notes/10.0.html>,
<https://documentation.suse.com/releasenotes/sles/html/releasenotes_sles_16.0/index.html>,
<https://docs.aws.amazon.com/linux/al2023/ug/system-requirements.html>,
<https://documentation.ubuntu.com/release-notes/26.04/summary-for-lts-users/>

### 1.9 기타

- dracut-ng: 최신 **dracut-112** (8월 2일, 연도 표기는 없지만 111이 2026-05-02이므로 2026년).
  분기 주기(2월, 5월, 8월). 원래 dracut은 2022년 이후 태그가 없고 openSUSE도
  dracut-ng로 옮겼다. 출처: <https://github.com/dracut-ng/dracut-ng/releases>,
  <https://bugzilla.redhat.com/show_bug.cgi?id=2444029>
- os-release(5): `ID`는 소문자/숫자/`._-`만, `SUPPORT_END=YYYY-MM-DD`(systemd 252+),
  `VENDOR_NAME`/`VENDOR_URL`(systemd 254+), `CPE_NAME`은 CPE URI 형식,
  `/etc/os-release`는 `/usr/lib/os-release`를 가리키는 상대 심볼릭 링크 권장.
  출처: <https://www.freedesktop.org/software/systemd/man/latest/os-release.html>

---

## 2. init, 기본 유저랜드, 핵심 라이브러리

### 2.1 systemd (LGPL-2.1-or-later 중심)

- 최신 **v262** (2026-09-22). 안정 브랜치를 여러 개 동시에 유지한다:
  v262.1(10-16), v261.4·v260.6·v259.10·v258.12(10-17).
- v262 README 요구사항:
  - 커널: 5.10 미만은 지원 안 함, 5.14 미만은 비권장(`old-kernel` taint)
  - libc: **glibc ≥ 2.34**, 또는 musl ≥ 1.2.6 (`-Dlibc=musl`)
  - 빌드: meson ≥ 0.62.0, ninja, python ≥ 3.9 + jinja2 (ukify는 pefile, systemd-boot는
    pyelftools 추가), gcc ≥ 8.4 또는 clang ≥ 13, binutils ≥ 2.35, gperf, pkg-config,
    libmount ≥ 2.30, libxcrypt ≥ 4.4.0, OpenSSL ≥ 3.0
  - 런타임: util-linux ≥ 2.27.1, **prefix는 `/usr`이어야 하며 split-usr/unmerged-usr는 지원 안 함**,
    nss-systemd 필수(`DynamicUser=`)
- musl 지원: v259(2025-12-17)에 "불완전한 지원" 추가. nss-systemd, nss-resolve,
  `DynamicUser=`, homed, userdbd 등은 동작하지 않으며 "지속 지원 약속 없음".
- 배포판에 영향이 큰 변화:

| 버전 | 변화 |
|---|---|
| v255 (2023-12) | split-usr/unmerged-usr 지원 제거, ukify 정식 |
| v256 | `/usr/sbin`이 `/usr/bin`과 분리되어 있으면 `unmerged-bin` taint |
| v258 (2025-09) | cgroup v1 제거 |
| v260 (2026-03) | SysV 스크립트·sysv-generator·rc-local 제거, 최소 커널 5.10/glibc 2.34/OpenSSL 3.0 |
| v261 | sysupdate 정식 표시 |
| v262 | sysupdate 다시 "실험적" 표시, sysupdated D-Bus API는 v263에서 제거 예정 |

출처: <https://raw.githubusercontent.com/systemd/systemd/main/NEWS>,
<https://raw.githubusercontent.com/systemd/systemd/v262/README>,
<https://github.com/systemd/systemd/releases>

### 2.2 다른 init

| | OpenRC | dinit | s6 + s6-rc | runit |
|---|---|---|---|---|
| 최신 | 0.64.1 (2026-09-23) | 0.22.1 (2026-07, 1.0 이전 베타) | s6 2.15.1.1 / s6-rc 0.8.0.2 (2026-10) | 2.3.1 (2026-02-07) |
| 사용처 | Alpine, Gentoo, Artix | Chimera, Artix | Artix | Void |
| 감독(supervision) | supervise-daemon | 있음 | 있음 | runsv |
| cgroup | v1/v2 | `run-in-cgroup` | 문서에서 확인 못 함 | 수동 |
| 로그 | 기본 없음 | 파일/버퍼/파이프 | s6-log | svlogd |

출처: <https://github.com/OpenRC/openrc/tags>, <https://raw.githubusercontent.com/davmac314/dinit/master/NEWS>,
<https://skarnet.org/software/s6/>, <https://smarden.org/runit/install.html>,
<https://chimera-linux.org/about/>

### 2.3 유저랜드

| 패키지 | 최신 |
|---|---|
| GNU coreutils | 9.12 (2026-09-14) |
| util-linux | 2.42.4 (2026-09-21) |
| BusyBox | 1.38.0 (2026-05-13, 업스트림 표기 "unstable"; 마지막 "stable"은 1.36.1) |
| toybox | 0.8.15 (2026-10-03) |
| uutils coreutils | 0.12.0 (2026-09-16), GNU 테스트 96.9% 통과 |
| findutils / grep / sed / tar | 4.11.0 / 3.12 / 4.10 / 1.35 |
| bash | 5.3 + 패치 020 (2026-09-14) |
| shadow | 4.20.3 (2026-09-23) |
| sudo | 안정판 1.9.17p2 (2025-07-26), 개발판 1.9.18rc1 (2026-01-17) |
| sudo-rs | 0.2.15 (2026-08-31) |

- Ubuntu 25.10: sudo-rs와 rust-coreutils를 기본으로 채택.
  26.04 LTS: rust-coreutils 0.8.0을 쓰되 **cp/mv/rm은 남은 TOCTOU 문제로 GNU 유지**,
  외부 감사에서 113건 발견, 릴리스 노트에 CVE 20건. 26.10: cp/mv/rm까지 Rust로 전환.

출처: <https://ftp.gnu.org/gnu/coreutils/>, <https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v2.42/>,
<https://busybox.net/>, <https://github.com/uutils/coreutils/releases>, <https://www.sudo.ws/>,
<https://raw.githubusercontent.com/trifectatechfoundation/sudo-rs/main/CHANGELOG.md>,
<https://documentation.ubuntu.com/release-notes/26.04/summary-for-lts-users/>,
<https://discourse.ubuntu.com/t/an-update-on-rust-coreutils/80773>

### 2.4 핵심 라이브러리와 빌드 도구

| 구성요소 | 사실 |
|---|---|
| OpenSSL | **3.5 LTS: 3.5.9, 2030-04-08까지.** 3.0 LTS는 2026-09-07 종료. 다음 LTS **4.2는 2027-04 예정, 2032-04까지.** FIPS 140-3 검증 provider: 3.1.2 |
| zlib | 1.3.2 (2026-02-17) |
| xz | 5.8.4 (2026-09-09), v5.8 브랜치만 유지. CVE-2024-3094(5.6.0/5.6.1 tarball 백도어) 이후 업스트림이 git 저장소에서 빌드해도 된다고 명시 |
| zstd | 1.5.7 (2025-02-19) |
| OpenSSH | 10.6 (2026-10-06) |
| libxcrypt | 4.5.2 (2025-11-10) |
| Linux-PAM | 1.7.3 (2026-09-24), 1.7.0부터 meson |
| Python | 3.15.1 (2026-10-21), 3.14.9 |
| Perl | 5.44.0 (2026-07-15) |
| meson | 1.12.1 (2026-09-22) |
| chrony | 4.9 (2026-08-27). systemd-timesyncd는 SNTP만 구현 |
| eudev | 3.2.15 (2026-09-27), 2023년 이후 첫 릴리스 |

출처: <https://openssl-library.org/source/>, <https://openssl-library.org/policies/releasestrat/index.html>,
<https://zlib.net/>, <https://tukaani.org/xz/>, <https://tukaani.org/xz-backdoor/>,
<https://github.com/facebook/zstd/releases>, <https://www.openssh.com/releasenotes.html>,
<https://www.python.org/downloads/>, <https://www.cpan.org/src/>, <https://chrony-project.org/news.html>,
<https://www.freedesktop.org/software/systemd/man/latest/systemd-timesyncd.service.html>

---

## 3. 보안, SBOM, 재현성, 지원 정책

### 3.1 강제 접근 제어(MAC)

| 항목 | 사실 |
|---|---|
| SELinux 유저스페이스 | 3.11 (2026-07-01) |
| refpolicy | 2.20260922 (2026-09-22), 연 3회 정도 릴리스 |
| 정책 계보 | Fedora/RHEL 정책은 refpolicy 기반의 큰 포크(커밋 약 2.8배). openSUSE 정책은 Fedora 정책의 하류. Debian은 refpolicy로 빌드 |
| AppArmor | 5.0.2 (2026-07-13), 4.1.8, 6.0.0-alpha1. Ubuntu·Debian 기본 |
| SUSE 전환 | Tumbleweed: 2025-02 스냅샷부터 신규 설치 SELinux enforcing 기본. **SLE 16: "AppArmor is removed"**, SELinux enforcing(400개 이상 모듈, 일부는 unconfined 허용). Leap 16.0도 SELinux 기본 |
| RHEL | enforcing이 기본이자 권장 |
| Landlock | 커널 7.3 문서에 ABI 11. 시스템 전체 MAC이 아니라 프로그램 스스로 쓰는 샌드박스 |

출처: <https://github.com/SELinuxProject/selinux/releases>, <https://github.com/SELinuxProject/refpolicy/releases>,
<https://github.com/fedora-selinux/selinux-policy>, <https://github.com/openSUSE/selinux-policy>,
<https://news.opensuse.org/2025/02/13/tw-plans-to-adopt-selinux-as-default/>,
<https://documentation.suse.com/sles/16.0/pdf/SLE-comparison_en.pdf>,
<https://kernel.org/doc/html/v7.3/userspace-api/landlock.html>

### 3.2 SBOM과 취약점 데이터

| 항목 | 사실 |
|---|---|
| SPDX | 최신 안정판 3.0.1 (2024-12-17), 3.1은 RC. ISO/IEC 5962:2021 |
| CycloneDX | 1.7 (2025-10-21) = ECMA-424 2판 |
| CISA SBOM 최소 요소 | **2026년판 최종(2026-07-29)**이 NTIA 2021판을 대체. 새 항목: SBOM 작성자 서명, 생성 맥락, 도구 이름/버전, 구성요소 해시, 구성요소 라이선스 등 |
| CSAF | 2.0이 OASIS 표준, 2.1은 아직 초안 |
| OpenVEX | v0.2.0, 스스로 "초안" 표기 |
| OSV 스키마 | 1.9.2 (2026-10-13), Alpine·Debian·Ubuntu·Red Hat·SUSE·Wolfi 등 생태계 포함 |
| 배포판 공지 형식 | Alpine: 브랜치별 secdb JSON. Wolfi: secdb형 `security.json` + OSV. Debian: JSON/OVAL/OSV. Ubuntu: OVAL/OSV/OpenVEX. Red Hat: CSAF + VEX(RHEL 10부터 OVAL 미제공). SUSE: CSAF/OVAL/OSV |
| 커널 CNA | 지원 중인 stable 트리의 수정마다 CVE를 붙이고, 영향 분석 없이 stable 업데이트 전체를 받으라고 안내. 2025년 Linux CNA 발행 5,686건(제3자 분석) |
| NVD | 2026-04-15부터 KEV·연방·핵심 소프트웨어 CVE만 우선 보강, 나머지는 "Not Scheduled" |

출처: <https://github.com/spdx/spdx-spec/releases>, <https://cyclonedx.org/specification/overview/>,
<https://www.cisa.gov/resources-tools/resources/2026-minimum-elements-software-bill-materials-sbom>,
<https://docs.oasis-open.org/csaf/csaf/v2.1/>, <https://github.com/openvex/spec>,
<https://ossf.github.io/osv-schema/>, <https://secdb.alpinelinux.org/>, <https://packages.wolfi.dev/os/security.json>,
<https://docs.kernel.org/process/cve.html>, <https://jerrygamblin.com/2026/01/01/2025-cve-data-review/>,
<https://www.nist.gov/news-events/news/2026/04/nist-updates-nvd-operations-address-record-cve-growth>

### 3.3 EU 사이버복원력법(CRA, Regulation (EU) 2024/2847)

| 날짜 | 적용 |
|---|---|
| 2026-09-11 | 제14조 보고 의무(실제 악용 취약점·중대 사고: 24시간 조기 경보, 72시간 통지) |
| 2027-12-11 | 나머지 전부(오픈소스 스튜어드 의무 포함) |

- 적용 범위는 "상업 활동으로" 공급되는 제품. 수익화하지 않는 FOSS, 이익을 재투자하는
  비영리는 상업 활동이 아님(전문 18). 저장소에 올려 두는 것만으로는 해당 안 됨(전문 20).
- 오픈소스 스튜어드는 **법인**이어야 함 → 개인 프로젝트는 스튜어드도 아님.
- 제조사가 되면: 운영체제는 **부속서 III Class I**, 지원 기간 최소 5년(제13조 8항),
  최소 최상위 의존성을 담은 SBOM. 기술 문서를 공개한 FOSS는 자가 평가 가능(제32조 5항).
- **KEL 시사점**: 수익화하지 않는 개인 프로젝트로 있는 동안은 의무가 없다. 다만 공개 기술
  문서와 SBOM을 처음부터 갖춰 두면 나중에 상업화해도 길이 열려 있다.

출처: <https://publications.europa.eu/resource/celex/32024R2847>,
<https://www.enisa.europa.eu/news/the-cra-single-reporting-platform-is-launched>

### 3.4 재현 가능한 빌드와 공급망

| 항목 | 사실 |
|---|---|
| SOURCE_DATE_EPOCH | 명세 1.1: 빌드는 내장 타임스탬프에 이 변수를 "반드시" 써야 함 |
| 도구 | diffoscope, reprotest, disorderfs, strip-nondeterminism, add-determinism, rebuilderd |
| Debian | amd64 main 테스트분의 98.0% 재현(reproduce.debian.net). 2026-05부터 재현 불가 신규 패키지는 testing 진입 차단 |
| Arch | core 91.9%, extra 87.9% |
| live-bootstrap | builder-hex0 → Fiwix → GNU Mes → tcc → gcc 4.0.4 → 4.7.4 → 10.5.0 → **gcc 15.2.0** (musl 1.2.5). x86 시드만, chroot/QEMU/실제 장비. "몇 시간 이상" 소요(사용자 보고 약 22시간) |
| StageX | 181바이트 시드 → live-bootstrap → 크로스 → 네이티브. 재현 가능, 여러 관리자가 서명 |
| Guix | 2023-04부터 357바이트 시드 기반 전체 소스 부트스트랩(x86_64/i686) |
| DDC | 결정적인 부모 컴파일러 + 독립적으로 신뢰할 수 있는 컴파일러 필요. GCC에서 시연됨 |
| SLSA | v1.2 (2025-11-24, Source 트랙 추가). Build L1: provenance 존재, L2: 호스팅 플랫폼이 서명, L3: 격리 빌드 + 빌드 단계에서 서명 키 접근 불가 |

출처: <https://reproducible-builds.org/specs/source-date-epoch/>, <https://reproducible-builds.org/tools/>,
<https://reproduce.debian.net/>, <https://reproducible.archlinux.org/api/v0/dashboard>,
<https://lists.debian.org/debian-devel-announce/2026/05/msg00001.html>,
<https://github.com/fosslinux/live-bootstrap>, <https://stagex.tools/>,
<https://guix.gnu.org/en/blog/2023/the-full-source-bootstrap-building-from-source-all-the-way-down/>,
<https://dwheeler.com/trusting-trust/>, <https://slsa.dev/spec/>

### 3.5 다른 배포판의 지원 정책

| 배포판 | 버전 체계 | 주기 | 지원 |
|---|---|---|---|
| RHEL | major.minor | 메이저 약 3년, 마이너 6개월 | 일반 5년, 유지보수 10년, 추가 계약 14년 (RHEL 10: 2035-05-31 유지보수 종료) |
| SLES 16 | 16.x | 마이너 매년 | 일반 지원 2035-11-30, LTS 2038, LTS Core 2041 |
| Ubuntu LTS | YY.MM | LTS 2년마다 | 표준 5년, Pro 10년, Legacy 15년 |
| Debian | 번호 + 코드명 | 약 2년 | 보안팀 약 3년, LTS 5년, ELTS(상용) 10년 |
| Alpine | 3.N | 5월·11월 | main 2년 |
| Amazon Linux 2023 | 2023.minor.YYYYMMDD | 분기별 마이너 | 표준 2027-06-30, 유지보수 2029-06-30 |
| Wolfi | 없음(롤링) | 계속 | 최신만, 이전 버전 6개월 보관 |

- 규모 참고: Debian LTS는 2026년 8월에 유급 기여자 19명이 공지 58건(CVE 1,885건)을 냈다.

출처: <https://access.redhat.com/support/policy/updates/errata>, <https://www.suse.com/lifecycle/>,
<https://ubuntu.com/about/release-cycle>, <https://wiki.debian.org/LTS>, <https://alpinelinux.org/releases/>,
<https://docs.aws.amazon.com/linux/al2023/ug/release-cadence.html>,
<https://www.freexian.com/blog/debian-lts-report-2026-08/>

---

## 4. 부팅, Secure Boot, 설치, 업데이트, 이미지, CI

### 4.1 부트로더

| 항목 | 사실 |
|---|---|
| GRUB | 최신 **2.14 (2026-01-14)**. EFI NX, shim loader protocol, **BLS·UKI 지원**, TPM2 키 보호, EROFS 추가 |
| systemd-boot | **UEFI 전용**. BLS Type #1 항목과 UKI(Type #2)를 부팅. Setup Mode에서 Secure Boot 키 등록 가능. **init이 systemd가 아니어도 쓸 수 있음**(Gentoo OpenRC, Alpine edge가 패키징) |
| Limine | BSD-2-Clause, BIOS+UEFI, x86-64/aarch64/riscv64/loongarch64, v12.9.4 (2026-10-19) |
| UKI | stub + 커널 + initrd + cmdline + os-release + `.sbat` 등을 PE 파일 하나로 묶어 통째로 서명. `ukify`로 생성·서명 |
| aarch64 서버 | Arm SystemReady/SBBR = UEFI + ACPI + SMBIOS → x86_64와 같은 UEFI 부팅 체인 |
| 레거시 BIOS | RHEL 10은 아직 지원. **SLES 16은 UEFI 기본, BIOS는 deprecated**("향후 제거") |

출처: <https://lists.gnu.org/archive/html/grub-devel/2026-01/msg00029.html>,
<https://cgit.git.savannah.gnu.org/cgit/grub.git/plain/NEWS?h=grub-2.14>,
<https://www.freedesktop.org/software/systemd/man/latest/systemd-boot.html>,
<https://wiki.gentoo.org/wiki/Systemd/systemd-boot>, <https://github.com/limine-bootloader/limine>,
<https://uapi-group.org/specifications/specs/unified_kernel_image/>,
<https://www.freedesktop.org/software/systemd/man/latest/ukify.html>,
<https://github.com/ARM-software/bbr-acs>, <https://documentation.suse.com/sles/16.0/html/SLE-comparison/>

### 4.2 Secure Boot

- **shim-review** 요구사항: shim 16.1 tarball에서 재현 가능한 빌드(`docker build .`),
  **법인 실체 증명(회사 등록) + Microsoft에 쓰는 EV 인증서**, 보안 연락처 2명(PGP로 확인),
  GRUB의 알려진 CVE 수정, Secure Boot에서 커널 lockdown 강제, 모든 바이너리에 SBAT,
  키 보호 방법(HSM 등). 리뷰어는 자원봉사자이고 "2~3개월 대기"가 있을 수 있다고 명시.
- **Microsoft 측**: Hardware Dev Center 등록에 EV 코드 서명 인증서와 회사 정보 필요.
  서명 키는 **FIPS 140-2 Level 2 이상 하드웨어**에 보관. GPLv3 코드는 서명 안 함(그래서 shim 필요).
  NX_COMPAT, `.sbom` PE 섹션의 서명된 SPDX SBOM 요구.
- **2011 → 2023 인증서 전환**: Microsoft UEFI CA 2011이 **2026-06-27 만료**. 앞으로의 제출은
  **UEFI CA 2023 서명만** 받는다 → db에 2023 CA가 없는 오래된 장비/VM에서는 새 shim이 부팅되지 않는다.
- **자체 키**: MOK(shim 기능이라 서명된 shim이 먼저 있어야 함), 또는 sbctl로 PK/KEK/db 직접 등록
  (펌웨어 Setup Mode 필요, `-m`으로 Microsoft 인증서 유지 권장).
- 조사 에이전트의 추정: 법인, EV 인증서, 두 번째 보안 연락처, FIPS 하드웨어가 준비된 뒤에도
  **전체 3~6개월**, shim을 바꿀 때마다 다시 리뷰.

출처: <https://github.com/rhboot/shim-review>,
<https://techcommunity.microsoft.com/blog/hardware-dev-center/updated-microsoft-uefi-signing-requirements/1062916>,
<https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-reqs>,
<https://support.microsoft.com/en-us/topic/windows-secure-boot-certificate-expiration-and-ca-updates-7ff40d33-95dc-4c3c-8725-a9b95457578e>,
<https://lwn.net/Articles/1079808/>, <https://github.com/Foxboron/sbctl>

### 4.3 설치 프로그램과 첫 부팅 설정

| 도구 | 사실 |
|---|---|
| **systemd-sysinstall** | **systemd 261에서 새로 생김.** 터미널 설치기: 디스크 선택 → systemd-repart로 파티션 → UKI와 systemd-boot 설치. `--confirm=no`로 무인 설치. 비밀번호는 systemd-firstboot나 credentials로 |
| systemd-repart | repart.d 파일로 파티션 선언, 반복 실행해도 안전, `SOURCE_DATE_EPOCH` + `--offline=yes`로 재현 가능한 이미지 생성 |
| Anaconda + kickstart | Fedora/RHEL용, DNF/RPM에 묶여 있고 무거움 |
| Calamares | 범용 그래픽 설치기 v3.4.3, 무인 모드 문서 없음 |
| Agama | SUSE의 새 설치기(SLES 16에서 YaST 대체) |
| cloud-init | v26.2, 주요 퍼블릭 클라우드와 NoCloud 지원 |
| Ignition + Afterburn | initramfs에서 첫 부팅 때 한 번 실행. Fedora CoreOS, Flatcar, SLE Micro 사용 |

출처: <https://www.freedesktop.org/software/systemd/man/latest/systemd-sysinstall.html>,
<https://www.freedesktop.org/software/systemd/man/latest/systemd-repart.html>,
<https://pykickstart.readthedocs.io/en/latest/kickstart-docs.html>, <https://calamares.io/>,
<https://agama-project.github.io/>, <https://docs.cloud-init.io/en/latest/>, <https://coreos.github.io/ignition/>

### 4.4 업데이트 방식

| 방식 | 사실 | 사용처 |
|---|---|---|
| OSTree / rpm-ostree | 내용 주소 기반 부팅 트리, 원자적 업그레이드와 롤백 | Fedora CoreOS, RHCOS |
| bootc | OCI 컨테이너 이미지로 트랜잭션 OS 업데이트. **CNCF Sandbox(2025-01)**, v1.17.1 | **RHEL image mode**(9.6+, 10). 패키지 모드와 이미지 모드는 서로 변환 불가 |
| systemd-sysupdate | A/B 파티션·파일 업데이트, SHA256SUMS 검증. **man 페이지에 "experimental"** | ParticleOS |
| Btrfs 스냅샷(transactional-update) | 새 스냅샷에 적용 후 재부팅, 롤백 가능 | openSUSE MicroOS, SLE Micro 6.2 |
| RAUC / SWUpdate / Mender | 임베디드용 A/B | IoT |
| 어플라이언스 A/B | Flatcar(update_engine), Bottlerocket(TUF, dm-verity), Talos | 컨테이너 호스트 |

출처: <https://ostreedev.github.io/ostree/>, <https://bootc.dev/bootc/>, <https://www.cncf.io/projects/bootc/>,
<https://developers.redhat.com/products/rhel-image-mode/faq>,
<https://www.freedesktop.org/software/systemd/man/latest/systemd-sysupdate.html>,
<https://github.com/openSUSE/transactional-update>, <https://github.com/bottlerocket-os/bottlerocket>

### 4.5 이미지/ISO 도구

- **mkosi v27.1** (2026-09-28): `Distribution=custom`으로 목록에 없는 배포판도 빌드 가능
  (base tree, skeleton tree, prepare 스크립트로 루트 채움). 출력: disk(systemd-repart), uki, esp, oci, sysext, tar.
- xorriso 1.5.8.pl02 (2026-05-24). Debian ISO 방식: x86_64는 BIOS El Torito + EFI El Torito +
  isohybrid MBR/GPT, aarch64는 EFI 전용 + ESP 파티션 덧붙임.
- KIWI NG 11.1.5는 Fedora/openSUSE/Ubuntu/Debian/Arch 등만 공식 지원.

출처: <https://github.com/systemd/mkosi/releases>,
<https://raw.githubusercontent.com/systemd/mkosi/main/mkosi/resources/man/mkosi.1.md>,
<https://ftp.gnu.org/gnu/xorriso/>, <https://wiki.debian.org/RepackBootableISO>, <https://osinside.github.io/kiwi/>

### 4.6 GitHub Actions (빌드 팜 대용 후보)

| 러너 | public 저장소 | private 저장소 |
|---|---|---|
| ubuntu-24.04 / 26.04 (x64) | **4 vCPU, 16 GB RAM, 14 GB SSD, 무료** | 2 vCPU, 8 GB, 14 GB |
| ubuntu-24.04-arm / 26.04-arm | **4 vCPU, 16 GB, 14 GB, 무료** | 2 vCPU, 8 GB, 무료 시간 소진 후 과금 |
| private 무료 한도(Free 플랜) | — | 월 2,000분, 저장 500 MB |

- 작업(job) 최대 **6시간**, 캐시 **저장소당 10 GB**(7일 미사용 시 삭제), 아티팩트 기본 90일 보관.
- 릴리스 첨부 파일: 파일당 2 GiB 미만, 릴리스당 1,000개, 전체 용량·대역폭 제한 없음.
  ghcr 컨테이너 레지스트리는 공개 패키지 "현재 무료".
- **x64 러너는 KVM 사용 가능**(udev 규칙 필요) → QEMU 부팅 테스트를 빠르게 돌릴 수 있음.
  **arm64 러너는 KVM 없음**(2026-08 "not planned"로 닫힘).

출처: <https://docs.github.com/en/actions/reference/runners/github-hosted-runners>,
<https://docs.github.com/en/billing/concepts/product-billing/github-actions>,
<https://docs.github.com/en/actions/reference/limits>,
<https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching>,
<https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases>,
<https://github.blog/changelog/2024-04-02-github-actions-hardware-accelerated-android-virtualization-now-available/>,
<https://github.com/actions/runner-images/issues/14062>

---

## 5. 패키지 매니저, 서명 도구, 빌드 시스템

### 5.1 apk-tools v3 현황

- **3.0.0 태그 2025-12-01**, 최신 3.0.8 (2026-08-31). 2.14 브랜치도 계속 유지(2.14.12, 2026-09-16).
- **Alpine**: 3.23.0(2025-12-03)부터 v3 도구를 쓰지만 "당분간 v2 색인·패키지 형식 유지".
  3.24/edge 미러는 여전히 v2 `APKINDEX.tar.gz`(RSA-4096, `.SIGN.RSA` = SHA-1 다이제스트에 RSA).
- **Chimera**: v3 도구 + **v3 형식**(ADB 색인 `Packages.adb`), cbuild가 `apk mkpkg`/`apk mkndx` 사용.
- **OpenWrt 25.12** (2026-03-05): opkg를 apk로 교체, v3 형식, **ECDSA P-256** 서명, mbedTLS로 빌드.
- **Wolfi**: apk-tools 2.14.10, v2 형식(RSA-4096 `.SIGN.RSA256`). melange도 v2 패키지 생성.
- postmarketOS는 2026-09-27 Nura로 이름 변경, Alpine 기반 유지.
- apk 3: GPL-2.0-only, C. 빌드 의존성 zlib + OpenSSL 또는 mbedTLS + 선택 zstd,
  meson 또는 **muon(Python 불필요)**으로 빌드.
- v3 서명: 메타데이터 트리의 SHA-512 다이제스트에 서명 하나, OpenSSL PEM 키(RSA/ECDSA).
- 롤백 기능 문서 없음, 디렉터리 glob 트리거와 commit 전후 훅 있음, 파일 충돌은 `replaces` 없으면 오류.
- 약점: v3 형식 문서가 얇고 "C 구조체 배치에 얽혀" 있음, libapk API가 v3에서 깨짐,
  저장소 메타데이터 유효기간(freeze/replay 방지) 없음.

### 5.2 패키지 매니저 비교

| | apk 3 | pacman 7 | RPM 6 + dnf5/tdnf | dpkg + apt 3 | xbps | opkg |
|---|---|---|---|---|---|---|
| 최신 | 3.0.8 | 7.1.0 | rpm 6.1.0 (2026-08-20), dnf5 5.4.6.0, tdnf 3.6.5 | apt 3.3.4, dpkg 1.23.11 | 0.60.7 | 0.10.0 |
| 언어 | C | C | rpm C++20, dnf5 C++, tdnf C | apt C++, dpkg C | C99 | C |
| 빌드 의존성 | zlib, OpenSSL/mbedTLS, (zstd) | libarchive, curl, gpgme, OpenSSL/nettle | CMake, popt, Lua, libarchive, sqlite, libmagic, debugedit, **rpm-sequoia(Rust) 없으면 서명·검증 불가** | apt: OpenSSL, db, lz4/xz/zstd, xxhash, seccomp, systemd, **sqv(Rust)** | zlib, OpenSSL, libarchive | CMake, curl, libsolv, gpgme |
| 서명 | v3: 메타데이터 트리 서명 | 패키지와 DB에 OpenPGP 분리 서명, 7.1부터 기본 필수 | 헤더에 OpenPGP, v6에서 패키지당 여러 서명 | InRelease 서명 + 해시 체인(.deb 자체는 무서명), `Valid-Until` | 패키지별 RSA, **색인 무서명** | 색인·패키지 서명 **기본 꺼짐** |
| 롤백 | 없음 | 없음 | dnf5 history undo/rollback | 없음 | 상태 기반 재개 | 없음 |
| 외부 채택 | Chimera, OpenWrt, Wolfi(v2), Nura | MSYS2 | Photon(tdnf), Azure Linux 4.0 프리뷰(dnf5 + rpm 6.0.1) | Debian 파생 | — | Yocto 기본 |

- **RPM 6.0 (2025-09-22)**: 서명 검사 기본 강제(`%_pkgverify_level all`), v6 형식 기본(SHA-3-256,
  MD5/SHA-1 제거), 패키지당 여러 서명, OpenPGP v6/PQC 키. **RPM 6.1**: PKCS#11 토큰 서명.
- **apt 3**: GnuPG 대신 sqv, 2030-02부터 RSA-2048 키 거부 정책.

### 5.3 서명 도구

| 도구 | 최신 | 특징 | 사용처 |
|---|---|---|---|
| GnuPG | 2.5.24 (2026-09-23), 2.4는 2026-06-30 EOL | OpenPGP | pacman, rpmsign 기본, tdnf, opkg |
| Sequoia sq/sqv | sq 1.5.0 (2026-10-07) | OpenPGP, Rust, 알고리즘 폐기 날짜 정책 | rpm 검증, apt |
| minisign | 0.12 | Ed25519, 신뢰 코멘트 | 패키지 매니저 사용처 확인 못 함 |
| signify | portable v33 | Ed25519, 다음 릴리스 키를 현재 서명된 릴리스에 넣는 방식 | OpenBSD 릴리스·pkg_add |
| Sigstore cosign | 3.1.4 | OIDC 기반 무키 서명 + 투명성 로그 | 주요 배포판 패키지 서명엔 미채택(2024-10 기준) |
| TUF | 명세 1.0.37 | root/targets/snapshot/timestamp 역할, 만료, freeze·rollback 공격 방어 | Bottlerocket, PyPI, Sigstore. **범용 배포판 패키지 매니저는 없음** |

- apk 저장소 키: Alpine RSA-4096(SHA-1 서명), Wolfi RSA-4096(SHA-256), Chimera RSA-2048(아키텍처별),
  OpenWrt ECDSA P-256.
- 조사한 기본 방식 중 저장소 메타데이터 신선도 검사를 문서화한 것은 apt(`Valid-Until`)뿐.

### 5.4 빌드 시스템과 격리

| 도구 | 레시피 | 언어 | 격리 | root 없이 | 크로스 | SBOM/재현성 | 라이선스 |
|---|---|---|---|---|---|---|---|
| abuild 3.17.0 | APKBUILD(sh) | sh | `rootbld`: bwrap | 예 | CHOST/CTARGET | — | GPL-2.0 |
| makepkg + devtools | PKGBUILD(bash) | bash | systemd-nspawn clean chroot | **아니오**(sudo) | 확인 못 함 | SOURCE_DATE_EPOCH 전달 | GPL |
| xbps-src | bash 템플릿 | bash | user namespace(기본) 또는 bwrap | 예, **root 실행 거부** | `-a` | — | BSD-2 |
| **cbuild** (Chimera) | template.py | **Python 3.12+** | **bwrap `--unshare-all`**, 읽기 전용 루트, 소스 받은 뒤 네트워크 없음 | 예, **root 실행 거부** | `-a ARCH` | 부트스트랩부터 다시 만든 bldroot가 동일 | BSD-2 |
| melange 0.63.1 | YAML | Go | bubblewrap(기본)/docker/qemu | 예 | 크로스 대신 QEMU | **패키지마다 SPDX SBOM** | Apache-2.0 |
| Portage | ebuild | Python+bash | LD_PRELOAD sandbox + namespace | 부분적 | crossdev | — | GPL-2.0 |
| BitBake (Yocto 6.0 LTS, 2030-04까지) | .bb | Python | user/network namespace + Landlock | **root 금지** | 크로스 중심 | SPDX 기본 | GPL-2.0 |
| Buildroot 2026.08 | Kconfig+make | make | 없음 | 예 | 크로스 중심 | CycloneDX 스크립트 | GPL-2.0+ |

- **bubblewrap 0.13.1** (2026-10-14). **0.12.0(2026-08-26)에서 setuid 지원을 없애고 LGPL-2.1+로
  재라이선스** → 비특권 user namespace가 필수. Flatpak, abuild, cbuild, melange, xbps-src가 사용.

출처: <https://github.com/alpinelinux/apk-tools>, <https://alpinelinux.org/posts/Alpine-3.23.0-released.html>,
<https://chimera-linux.org/docs/apk>, <https://openwrt.org/releases/25.12/notes-25.12.0>,
<https://github.com/wolfi-dev/os/blob/main/apk-tools.yaml>, <https://rpm.org/releases/6.0.0>,
<https://rpm.org/releases/6.1.0>, <https://github.com/rpm-software-management/rpm>,
<https://github.com/rpm-software-management/dnf5>, <https://github.com/vmware/tdnf>,
<https://learn.microsoft.com/en-us/azure/azure-linux/whats-new-azure-linux-4>,
<https://gitlab.archlinux.org/pacman/pacman>, <https://salsa.debian.org/apt-team/apt>,
<https://github.com/void-linux/xbps>, <https://gnupg.org/download/index.html>,
<https://theupdateframework.github.io/specification/latest/>, <https://theupdateframework.io/adoptions/>,
<https://github.com/alpinelinux/abuild>, <https://raw.githubusercontent.com/chimera-linux/cports/master/Usage.md>,
<https://github.com/chainguard-dev/melange>, <https://wiki.yoctoproject.org/wiki/Releases>,
<https://github.com/containers/bubblewrap>
