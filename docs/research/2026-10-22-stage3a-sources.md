# Stage 3a 소스 검증 기록 (2026-10-22)

LFS 12.4 7장에 해당하는 stage 3a 레시피 6개(gettext, bison, perl, python, texinfo,
util-linux)의 소스를 받아 sha256과 서명을 직접 확인한 기록이다. 레시피의 `sha256`은
여기서 계산한 값이다. 키 출처는 `keys/upstream/README.md`에 있다.

## 결과 요약

| 패키지 | 버전 | 검증 방식 | 결과 |
|---|---|---|---|
| gettext | 1.0 | GNU `.sig` (Bruno Haible `E0FFBD97…AC08`) | GOODSIG, VALIDSIG |
| bison | 3.8.2 | GNU `.sig` (Akim Demaille `7DF84374…264E`) | GOODSIG. DSA-1024 키와 SHA-1 digest라 강도는 낮다 |
| texinfo | 7.3 | GNU `.sig` (Gavin Smith `EAF669B3…FBA9`) | GOODSIG, VALIDSIG |
| util-linux | 2.42.4 | 압축 푼 tar에 대한 `.tar.sign` (Karel Zak `B0C64D14…C284`) | GOODSIG. kernel.org autosigner의 `sha256sums.asc`도 같은 sha256 |
| perl | 5.44.0 | PAUSE가 clearsign한 `CHECKSUMS` (`2E66557A…89EC`) | GOODSIG. 서명된 본문에 `.tar.xz`의 sha256이 그대로 있다 |
| python | 3.15.1 | Sigstore (PEP 761) | sigstore-python 4.5.1로 `hugo@python.org` 신원 확인. kel은 sha256만 강제 |

xz 무결성(`xz -t`)은 여섯 개 모두 통과했다.

## 패키지별 메모

### util-linux

- kernel.org는 압축 푼 tar에 서명한다. 레시피는 `signature_type = "detached-uncompressed"`.
- 키는 kernel.org pgpkeys 저장소의 `keys/E4B71D5EEC39C284.asc`. 같은 키를 kernel.org WKD에서
  받으면 오래된 사본이라 `EXPKEYSIG`가 나지만 서명 자체는 유효하다.
- 추가 확인: `sha256sums.asc`(Kernel.org checksum autosigner `B8868C80…DA6B1`)의 항목과
  계산한 sha256이 같다.

### perl

- CPAN은 tarball에 OpenPGP 서명을 따로 붙이지 않는다. 업로더(LEONT) 디렉터리의
  `CHECKSUMS`를 PAUSE가 clearsign하고, 여기에 `perl-5.44.0.tar.xz`의 sha256과 크기가 있다.
- pause.perl.org와 cpan.org의 키 블록은 2026-07-02 만료로 표시되고 2026년 부키가 없어
  `NO_PUBKEY`가 났다. 같은 주 키의 최신 사본을 keyserver.ubuntu.com에서 받아 검증했다.
  서명 부키는 `4584D789E682F9F53B392F1837D079412CC9032E`.
- 그래서 kel에 `clearsigned-checksums` 검증 방식을 추가했다(`tools/kel/fetch.py`의
  `gpg_verify_clearsigned`). 서명이 유효하고, 검증된 본문에 파일 이름과 고정한 sha256이
  모두 있어야 통과한다.
- Sigstore 번들도 확인했다. 서명 신원은 `fawaka@gmail.com`(Leon Timmermans, MetaCPAN과
  tarball의 `Porting/core-team.json`으로 대조). 그런데 `.tar.xz.sigstore.bundle`은 `.tar.gz`의
  digest에 서명되어 있어서 `.tar.xz`와 짝지으면 "Bundle message digest mismatch"로 실패한다.
  `.tar.gz`와는 맞는다. 업스트림 실수로 보이고, kel은 PAUSE `CHECKSUMS`를 쓴다.
- 압축을 푼 tar의 sha256(`7da0fe0c…465b`)이 `.tar.xz`와 `.tar.gz` 양쪽에서 같고, PAUSE가
  서명한 `sha256-ungz` 값과도 같다.

### python

- Python 3.14부터 릴리스는 Sigstore로만 서명한다(PEP 761). kel은 표준 라이브러리만 쓰므로
  지금은 Sigstore를 직접 검증하지 못한다.
- `Python-3.15.1.tar.xz.sigstore`를 sigstore-python 4.5.1로 확인했다. 신원 `hugo@python.org`,
  발급자 `https://github.com/login/oauth`. 다른 릴리스 관리자 신원으로 검증하면 실패하는 것도
  확인했다(대조군).
- python.org 릴리스 페이지의 SHA-256과 계산한 값이 같다.
- Python 3.15는 libmpdec를 더 이상 같이 넣지 않는다. stage 3a에서는 `_decimal`이 빠진 채로
  두고, stage 3b에서 mpdecimal을 패키지로 만든 뒤 다시 빌드한다.

## 남은 일

- Sigstore 검증을 kel에 넣는 방법(외부 도구를 빌드 의존성으로 둘지, 최소 검증기를 만들지)은
  Phase 4에서 정한다.
- DSA-1024 키(bison, PAUSE)는 sha256 고정이 실제 방어선이다. 업스트림이 키를 바꾸면 따라간다.
