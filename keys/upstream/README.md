# 업스트림 서명 공개 키

레시피의 `signing_keys`에 적힌 지문(fingerprint)의 공개 키다. 파일 이름은
`<40자리 지문>.asc`이고, `kel`은 소스 서명을 검증할 때 레시피에 적힌 키만
임시 keyring에 넣어 확인한다(`tools/kel/fetch.py`). 개인 키는 여기에 두지 않는다.

| 지문 | 주인 | 쓰는 레시피 | 가져온 곳 |
|---|---|---|---|
| `3A24BC1E8FB409FA9F14371813FCEF89DD9E3C4F` | Nick Clifton (binutils 관리자) | binutils | GNU keyring |
| `13975A70E63C361C73AE69EF6EEB81F8981C74C7` | Richard Guenther (GCC 릴리스) | gcc | GNU keyring |
| `343C2FF0FBEE5EC2EDBEF399F3599FF828C67298` | Niels Möller (GMP) | gcc (in-tree GMP) | GNU keyring |
| `A534BE3F83E241D918280AEB5831D11A0D4DB02A` | Vincent Lefevre (MPFR) | gcc (in-tree MPFR) | GNU keyring |
| `AD17A21EF8AED8F1CC02DBD9F7D5C9BF765C61E3` | Andreas Enge (MPC) | gcc (in-tree MPC) | GNU keyring |
| `35B17DF5752577CA0C541CEB94BFDF4484AD142F` | Andreas K. Huettel (glibc 릴리스) | glibc | GNU keyring |
| `647F28654894E3BD457199BE38DBBDC86092693E` | Greg Kroah-Hartman (stable 커널) | linux | kernel.org pgpkeys 저장소 |
| `71C2CC22B1C4602927D2F3AAA7A16B4A2527436A` | Eric Blake | m4 | GNU keyring |
| `19882D92DDA4C400C22C0D56CC2AF4472167BE03` | Thomas E. Dickey | ncurses | <https://invisible-island.net/public/dickey@invisible-island.net-rsa3072.asc> (GNU keyring 사본은 만료) |
| `7C0135FB088AAF6C66C650B9BB5869F064EA74AB` | Chet Ramey | bash (tarball과 공식 패치) | GNU keyring |
| `6C37DC12121A5006BC1DB804DF6FD971306037D9` | Pádraig Brady | coreutils | GNU keyring |
| `155D3FC500C834486D1EEA677FD9FCCB000BEEEE` | Jim Meyering | diffutils, grep, gzip, sed | GNU keyring |
| `BE04995BA8F90ED0C0C176C471112AB16CB33B3A` | Christos Zoulas | file | keys.openpgp.org와 keyserver.ubuntu.com (같은 키, 만료 표시) |
| `0CF4E8D871593224842832B888DD9E08C5DDACB9` | James Youngman | findutils | GNU keyring |
| `D1967C63788713177D861ED7DF597815937EC0D2` | Arnold Robbins | gawk | GNU keyring |
| `6D4EEB02AD834703510B117680CB727A20C79BB2` | Paul D. Smith | make | GNU keyring, Savannah (서명 부키 2026-10-20 만료) |
| `259B3792B3D6D319212CC4DCD5BF9FEB0313653A` | Andreas Gruenbacher | patch, attr, acl | Savannah user 15000과 kernel.org pgpkeys `keys/D5BF9FEB0313653A.asc`(2029-07-16까지)를 합침. GNU keyring 사본은 만료 |
| `325F650C4C2B6AD58807327A3602B07F55D0C732` | Sergey Poznyakoff | tar | GNU keyring |
| `3690C240CE51B4670D30AD1C38EE757D69184620` | Lasse Collin | xz | <https://tukaani.org/misc/lasse_collin_pubkey.txt> |
| `E0FFBD975397F77A32AB76ECB6301D9E1BBEAC08` | Bruno Haible | gettext | GNU keyring |
| `7DF84374B1EE1F9764BBE25D0DDCAA3278D5264E` | Akim Demaille | bison | GNU keyring |
| `EAF669B31E31E1DECBD11513DDBC579DAB37FBA9` | Gavin Smith (Texinfo 관리자) | texinfo | GNU keyring |
| `B0C64D14301CC6EFAEDF60E4E4B71D5EEC39C284` | Karel Zak | util-linux | kernel.org pgpkeys 저장소 `keys/E4B71D5EEC39C284.asc` |
| `2E66557AB97C19C791AF8E20328DA867450F89EC` | PAUSE Batch Signing Key (CPAN) | perl (서명된 `CHECKSUMS`) | keyserver.ubuntu.com (아래 참고) |
| `5ED46A6721D365587791E2AA783FCD8E58BCAFBA` | Mark Adler | zlib | <https://madler.net/madler/pgp.html> (zlib.net이 링크). DSA-1024 |
| `EC3CFE88F6CA0788774F5C1D1AA44BE649DE760A` | Mark Wielaard | bzip2 | <https://sourceware.org/pub/bzip2/gpgkey-5C1D1AA44BE649DE760A.gpg> (다운로드 페이지에 명시) |
| `4EF4AC63455FC9F4545D9B7DEF8FE99528B52FFD` | Zstandard Release Signing Key | zstd | keyserver.ubuntu.com. Debian이 같은 키를 고정(`debian/upstream/signing-key.asc`) |
| `FF360647C7A7147F27DAAEC1B132F881C306590A` | Gavin D. Howard | bc | keyserver.ubuntu.com만 있음(프로젝트가 키를 문서화하지 않음). sha256 고정이 주된 근거 |
| `56C67868E93390AA1039AD1CE4B29C8D64885307` | Will Estes | flex | keyserver.ubuntu.com. Debian이 같은 키를 고정 |
| `38A644698C69787344E954CE29EE848AE2CCF3F4` | Andrew G. Morgan | libcap | kernel.org pgpkeys `keys/29EE848AE2CCF3F4.asc` |
| `678CE3FEE430311596DB8C16F52E98007594C21D` | Björn Esser | libxcrypt | 릴리스 첨부 `libxcrypt-gpgkey.asc`. 소스의 `make release`에 같은 키 ID가 박혀 있음 |
| `A9348594CE31283A826FBDD8D57633D441E25BB5` | Alejandro Colomar | shadow | 저장소의 `keys/A9348594….asc` (`AUTHORS.md`가 가리킴) |
| `5D2FB320B825D93904D205193938F96BDF50FEA5` | Craig Small | psmisc, procps-ng | keys.openpgp.org(만료일이 2028-09-16로 연장된 사본). GitLab과 keyserver.ubuntu.com 사본은 2026-10-17 만료 |
| `FA26CA784BE188927F22B99F6570EA01146F7354` | Ileana Dumitrescu | libtool | GNU keyring과 Savannah 회원 키 목록(만료 연장본)을 합침 |
| `4BE4E62655488EB92ABB468F79FFD94BFCE230B1` | Sergey Poznyakoff | gdbm | GNU keyring |
| `3176EF7DB2367F1FCA4F306B1F9B0E909AF37285` | Sebastian Pipping | expat | keys.openpgp.org. Gentoo 개발자 키 디렉터리(WKD)에서도 같은 결과 |
| `AE27252BD6846E7D6EAE1DD6F153A7C833235259` | Mark Nudelman | less | <https://www.greenwoodsoftware.com/less/pubkey.asc> (다운로드 페이지가 링크). DSA-1024 |
| `82F854F3CE73174B8B63174091FCC32B6769AA64` | Zack Weinberg | autoconf | GNU keyring |
| `6C222EA6B2BD216AA406516AC868F0B6DE38409D` | Kamila Szewczyk | automake | GNU keyring |
| `B146647E45A7B33947AB226B2A2C87D161692D40` | OpenSSL | openssl | <https://openssl-library.org/source/pubkeys.asc> (소스 페이지가 신뢰 기준으로 이 지문을 명시) |
| `6C2B631563B8D330578D3CB474FD3FA2779E7073` | Aaron Merey | elfutils | keyserver.ubuntu.com. 이전 릴리스(0.191, 0.193, 0.196)와 0.197 공지도 같은 키로 서명됨 |
| `19E2D6D9B46D8DAA6288F877C24E631BABB1FE70` | Jussi Pakkanen | meson | keyserver.ubuntu.com. 서명된 git 태그 1.12.1도 같은 키 |
| `EAB33C9690013C733916AC839BA2A5A630CBEA53` | Lucas De Marchi | kmod | kernel.org pgpkeys `keys/9BA2A5A630CBEA53.asc` |
| `9F6FC345B05BE7E766B83C8F80A77F6095CDE47E` | Stephen Hemminger | iproute2 | kernel.org pgpkeys `keys/80A77F6095CDE47E.asc` |
| `3AB057B7E78D945C8C5591FBD36F769BC11804F0` | Theodore Ts'o | e2fsprogs | kernel.org pgpkeys `keys/D36F769BC11804F0.asc` |

- GNU keyring: <https://ftp.gnu.org/gnu/gnu-keyring.gpg> (2026-10-22에 받음)
- kernel.org pgpkeys: <https://git.kernel.org/pub/scm/docs/kernel/pgpkeys.git/plain/keys/38DBBDC86092693E.asc>
- 키는 `gpg --armor --export <지문>`으로 **전체**를 내보낸다. `export-minimal`은 쓰지 않는다:
  만료된 부키(subkey)가 빠지는데, glibc 2.44는 만료 표시된 서명 부키
  (`FD19E6D31B192EE4DC63EAD3DC2B16215ED5412A`)로 서명되어 있어 검증이 실패했다(2026-10-22 확인).

## 만료 표시에 대하여

GNU keyring에 든 일부 키 사본(Niels Möller, Andreas Enge, Andreas K. Huettel)은
만료로 표시된다. 키 주인이 만료일을 연장했어도 keyring 사본이 오래되면 이렇게 보인다.
`kel`은 sha256 고정과 지문 고정을 신뢰의 근거로 삼기 때문에, 만료 표시가 있어도 유효한
서명(VALIDSIG)이면 받아들이고 경고를 남긴다. 폐기(REVKEYSIG)나 잘못된 서명은 거부한다.

## PAUSE 키(perl)에 대하여

perl은 tarball에 대한 OpenPGP 서명을 따로 내지 않는다. 대신 CPAN의 업로드 서버 PAUSE가
저자 디렉터리마다 `CHECKSUMS` 파일을 만들어 clearsign하고, 여기에 각 파일의 sha256이 들어 있다.
레시피는 `signature_type = "clearsigned-checksums"`로 이 파일을 검증하고, 검증된 본문에
파일 이름과 고정한 sha256이 함께 들어 있는지 확인한다(`gpg_verify_clearsigned`).

- pause.perl.org와 cpan.org에 올라 있는 키 블록(둘은 같다)은 오래된 사본이다. 2026-07-02에
  만료로 표시되고 2026년 서명 부키가 없어서, 그 블록만으로는 `NO_PUBKEY`가 난다(2026-10-22 확인).
- 그래서 같은 주 키(primary)의 최신 사본을 keyserver.ubuntu.com에서 받았다. keys.openpgp.org에도
  같은 부키가 있다. 부키의 binding 서명은 공식 사이트의 주 키로 검증된다.
- 주 키가 DSA-1024라서 강도는 낮다. 그래서 perl 소스는 sha256 고정에 더 크게 기대고,
  Phase 4에서 Sigstore 검증을 도구에 넣을 때 다시 본다. 업스트림 Sigstore 번들은 2026-10-22 기준으로
  `.tar.xz`용 번들이 `.tar.gz`의 digest에 서명되어 있어 그대로는 쓸 수 없었다
  (`docs/research/2026-10-22-stage3a-sources.md` 참고).

## 새 키를 추가할 때

1. 키를 공식 경로(프로젝트 웹사이트, GNU keyring, kernel.org 등)에서 받는다.
2. 서명 검증이 되는지 확인하고, 지문을 프로젝트 공식 문서와 대조한다.
3. 위 방식으로 내보내 `<지문>.asc`로 저장하고 이 표에 출처를 적는다.
