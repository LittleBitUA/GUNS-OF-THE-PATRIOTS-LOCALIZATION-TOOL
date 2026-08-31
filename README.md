# Guns of the Patriots Localization Tool

**Work in progress.** Tools for translating **METAL GEAR SOLID 4: Guns of the
Patriots — Master Collection Version (PC)** into your language.

We are making a **Ukrainian** translation of MGS4, and along the way we had to
work out how the PC release stores its **textures** and **text**. This
repository shares those tools, plus a plain-language FAQ of what each container
is and how it is put together, so other teams translating into other languages
do not have to rediscover it from scratch.

Made in Ukraine by **Dmytro Bidlov** — [Little Bit Team](https://t.me/LittleBitUA)

> *(Українською — [нижче](#guns-of-the-patriots-localization-tool-українською).)*

---

## What is in here

Two independent toolsets:

- **Text** — export the in-game strings to editable `.txt`, translate them, and
  import them back. Every string has a byte-length field the game reads; the
  importer recomputes it, so a translated line of any length loads correctly.
- **Textures** — unpack the texture archives, edit an image, and inject it back
  without corrupting the archive.

**Nothing here writes into the game on its own.** Every tool reads from the game
and writes its output to a folder you choose. You copy the result into the game
yourself. Back up the file you are replacing first.

## Requirements

```
python 3.10+
pip install numpy pillow lz4
```

The tools find your install automatically by scanning your Steam libraries. If
that fails, point them at it:

```
set MGS4_DIR=D:\SteamLibrary\steamapps\common\METAL GEAR SOLID 4\MGS4
```

---

## Text: translate the dialogue and menus

The strings live in five container families under
`common\localization\{codec,lang,spc,demo,movie}`, one file per language
(`codec_en`, `lang_en`, ...). Nothing is encrypted.

**Export a container to an editable text file:**

```
python src/text_tool.py export codec_en  work/codec_en.txt
```

Each string becomes a block:

```
### 0
Original English text here.

### 1
Next string.
```

Translate the lines under each `###` header, keep the header. A block you leave
unchanged is written back byte-for-byte.

**Import the translation into a new container file:**

```
python src/text_tool.py import codec_en  work/codec_en.txt  build/codec_en
```

Then copy `build/codec_en` over `common\localization\codec\codec_en` in the
game (back up the original first). Repeat for `lang`, `spc`, `demo`, `movie`.

**Prove the tool is faithful** — a no-op rebuild is byte-identical to the
original:

```
python src/text_tool.py verify codec_en
```

> **Tip on line length.** A few short on-screen labels (checkpoint / pause /
> HUD text) are drawn into a fixed-size buffer. If a translation of one of
> those is longer than the original *in characters*, the game can crash when it
> is shown. Long dialogue is fine; keep short UI labels at or under the
> original length.

---

## Textures: replace an image

**1. Unpack a texture tree** (writes DDS + an inventory beside them):

```
python src/txnup_unpack.py "%MGS4_DIR%\common\textures\PC_TXN_UP" unpack/common
```

You now have every texture as a `.dds` under `unpack/common/dds/...` and an
`inventory.tsv` recording each texture's real format, size and source blob. Do
this once; the inject tools read that inventory.

**2. Export a texture to a lossless PNG, edit it, inject it back:**

```
python src/txn_png.py export --txn title/cache/0015161c.txn
#   ... edit edit/0015161c_00_2048x2048_DXT5.png in any editor, keep it PNG ...
python src/txn_png.py inject edited.png --txn title/cache/0015161c.txn --apply
```

`inject` re-encodes only the 4x4 blocks you actually changed, matches the exact
format and mip chain the game expects, and relocates the blob inside the
archive if the edit no longer fits its slot (it usually does not — see the
FAQ). Every copy of the texture in the archive is updated together.

---

## The scripts

| script | what it does |
|---|---|
| `text_tool.py` | export / import / verify the five text containers |
| `txnup_unpack.py` | unpack a whole `PC_TXN_UP` tree to DDS + `inventory.tsv` |
| `txn_png.py` | lossless PNG round trip for a texture — export, edit, inject |
| `txn_inject.py` | the texture rebuild helpers (format, mips, block patching) |
| `vpak.py` | read a VPAK archive: table of contents, per-entry decompression |
| `vpak_append.py` | relocate a blob that grew past its slot |
| `pak_extract.py` | extract any other VPAK (stage data, sound, shaders) whole |
| `txnup_fonts.py`, `txnup_fonts_strict.py` | find glyph-atlas textures |
| `master_index.py` | one browsable index over everything unpacked |
| `mgstex.py`, `mgsbc.py` | DDS math, BC1/BC3 decode (via Pillow) and encode |
| `mgs4paths.py` | locate the game install |

## How the formats work — FAQ

The full write-up is in **[docs/FORMATS.md](docs/FORMATS.md)**. The short
version:

**Where are the textures?** In VPAK archives (`*.pak`). Each `PC_TXN_UP` folder
has an *index* pair (`txn_up.1.pak`, `txn_up.2.pak`) full of `.txn` descriptors
and a *data* pak (`paks/TextureData.pak`) full of the pixel blobs.

**Are there two of everything?** Yes. The Master Collection keeps an older
descriptor layer in `stage_data_compressed` and higher-resolution replacements
in `PC_TXN_UP`. The `PC_TXN_UP` copy is the one that renders, and it supersedes
the older layer for 98.7% of textures. There are 9,973 `.txn` across four
archive layers in total.

**Why does an edited texture never fit back?** The stock art is extremely
compressible — a 699 KB texture can be stored in 54 KB, almost 13:1, because it
is mostly flat colour. Any real edit breaks those long runs, so the compressed
result no longer fits its slot. The tools handle this by relocating the blob
and updating its offset in the table of contents.

**Why did my edit look grainy or blotchy?** Two traps. First, saving the DDS in
the wrong format (an editor defaults to DXT5; a given texture may be DXT1) or
saving without mipmaps — the tools rebuild both. Second, going
DDS → edit → DDS re-encodes the block compression several times and each pass
degrades it; the PNG round trip does it once. Use `txn_png.py`.

**Why does my text edit crash the game?** Almost always a short on-screen label
that got longer — see the length tip above. Long dialogue does not have this
problem.

**Do fonts live with the textures?** Yes — the fonts are textures. There are
about 20 distinct glyph atlases, duplicated into 336 copies across the game.
`txnup_fonts_strict.py` finds them. Patch **every copy**, not only the screens
you walked through: an unpatched sheet is what puts `ä´ä°` on screen where a
word should be.

**How does the game actually draw a letter?** By the **raw byte**. There is no
code-point lookup — the byte indexes a cell in the atlas directly. So an
alphabet outside Latin-1 needs its own single-byte code page, painted into free
cells of the sheet. The whole procedure, the traps, and a table that tells you
which mistake you made from what you see on screen are in
**[docs/FONTS.md](docs/FONTS.md)**.

**My translated line vanished completely — why?** The game draws some widgets
with a bitmap atlas and others with a TrueType face. A single-byte string sent
to a TrueType widget is not valid UTF-8, so the engine drops the whole string;
if the line begins with ASCII, only that prefix survives. The opposite mistake
(UTF-8 into a bitmap widget) draws one glyph per two bytes, with gaps.

**Then how do I tell which renderer a string uses?** It is **not recorded in
the text files** — we checked four ways, and `docs/FONTS.md` lists them. The
widget id is the best predictor available; individual keys inside one widget
can go the other way, so keep a short per-key exception list.

**Are the mipmaps where I expect them?** No. A texture cache is split across a
pair of `.dlz` files: `<name>_d.dlz` holds mip 0 on its own and `<name>.dlz`
holds the rest, so a naive concatenation gives you the chain backwards. Pair
them by the `parent` field in the entry header, which states exactly how many
bytes belong in front. Details in [docs/FORMATS.md](docs/FORMATS.md).

---
---

# Guns of the Patriots Localization Tool (українською)

**Робота триває.** Інструменти для перекладу **METAL GEAR SOLID 4: Guns of the
Patriots — Master Collection Version (PC)** вашою мовою.

Ми робимо **український** переклад MGS4, і дорогою довелося розібратися, як
PC-видання зберігає **текстури** й **текст**. У цьому репозиторії ми ділимося
цими інструментами та зрозумілим FAQ про те, що таке кожен контейнер і як він
влаштований, — щоб інші команди не відкривали це заново.

Зроблено в Україні Дмитром Бидловим — [Little Bit Team](https://t.me/LittleBitUA)

## Що тут є

Два незалежні набори:

- **Текст** — вивантаження ігрових рядків у редагований `.txt`, переклад і
  завантаження назад. Кожен рядок має поле довжини в байтах, яке читає гра;
  імпортер його перераховує, тож перекладений рядок будь-якої довжини
  завантажиться правильно.
- **Текстури** — розпакування текстурних архівів, редагування зображення й
  вставка назад без пошкодження архіву.

**У теку гри тут нічого не пишеться саме собою.** Кожен інструмент читає з гри
й пише результат у теку, яку ти обереш. Копіюєш результат у гру сам. Спершу
зроби резервну копію файлу, який заміняєш.

## Що потрібно

```
python 3.10+
pip install numpy pillow lz4
```

Інструменти самі знаходять гру, скануючи бібліотеки Steam. Якщо не вийшло —
вкажи шлях:

```
set MGS4_DIR=D:\SteamLibrary\steamapps\common\METAL GEAR SOLID 4\MGS4
```

## Текст: переклад діалогів і меню

Рядки лежать у п'яти родинах контейнерів у
`common\localization\{codec,lang,spc,demo,movie}`, по файлу на мову
(`codec_en`, `lang_en`, ...). Нічого не зашифровано.

**Вивантажити контейнер у редагований текст:**

```
python src/text_tool.py export codec_en  work/codec_en.txt
```

Кожен рядок стає блоком:

```
### 0
Оригінальний англійський текст.

### 1
Наступний рядок.
```

Перекладай рядки під кожним заголовком `###`, заголовок лишай. Блок, який ти не
змінив, записується назад байт-у-байт.

**Завантажити переклад у новий файл контейнера:**

```
python src/text_tool.py import codec_en  work/codec_en.txt  build/codec_en
```

Потім скопіюй `build/codec_en` поверх `common\localization\codec\codec_en` у
грі (спершу резервна копія оригіналу). Повтори для `lang`, `spc`, `demo`,
`movie`.

**Переконатися, що інструмент точний** — перезбірка без змін побайтово тотожна:

```
python src/text_tool.py verify codec_en
```

> **Про довжину рядка.** Кілька коротких екранних написів (контрольна точка /
> пауза / HUD) малюються в буфер фіксованого розміру. Якщо переклад одного з
> них довший за оригінал *у символах*, гра може вилетіти в момент показу.
> Довгі діалоги — без проблем; короткі написи інтерфейсу тримай у межах
> довжини оригіналу.

## Текстури: заміна зображення

**1. Розпакувати дерево текстур** (пише DDS + інвентар поруч):

```
python src/txnup_unpack.py "%MGS4_DIR%\common\textures\PC_TXN_UP" unpack/common
```

Тепер кожна текстура — це `.dds` у `unpack/common/dds/...`, а `inventory.tsv`
записує справжній формат, розмір і блоб кожної. Роби це один раз.

**2. Вивантажити текстуру в PNG без втрат, відредагувати, вставити назад:**

```
python src/txn_png.py export --txn title/cache/0015161c.txn
#   ... редагуєш edit/0015161c_00_2048x2048_DXT5.png, лишаєш PNG ...
python src/txn_png.py inject edited.png --txn title/cache/0015161c.txn --apply
```

`inject` перекодовує лише блоки 4x4, які ти справді змінив, точно відповідає
формату та мип-ланцюгу гри, і переносить блоб усередині архіву, якщо правка
більше не влазить у слот. Усі копії текстури оновлюються разом.

## Скрипти

| скрипт | що робить |
|---|---|
| `text_tool.py` | експорт / імпорт / перевірка п'яти текстових контейнерів |
| `txnup_unpack.py` | розпакувати дерево `PC_TXN_UP` у DDS + `inventory.tsv` |
| `txn_png.py` | обмін текстури через PNG без втрат — експорт, правка, вставка |
| `txn_inject.py` | помічники перезбірки текстур (формат, мипи, патч блоків) |
| `vpak.py` | читання архіву VPAK: зміст, розпакування записів |
| `vpak_append.py` | перенести блоб, що виріс за межі слота |
| `pak_extract.py` | витягти будь-який інший VPAK (stage, звук, шейдери) |
| `txnup_fonts.py`, `txnup_fonts_strict.py` | знайти текстури-атласи гліфів |
| `master_index.py` | єдиний індекс усього розпакованого |
| `mgstex.py`, `mgsbc.py` | арифметика DDS, декодування BC1/BC3 і кодування |
| `mgs4paths.py` | знайти встановлену гру |

## Як влаштовані формати — FAQ

Повний розбір — у **[docs/FORMATS.md](docs/FORMATS.md)**. Коротко:

**Де текстури?** В архівах VPAK (`*.pak`). Кожна тека `PC_TXN_UP` має пару
*індексів* (`txn_up.1.pak`, `txn_up.2.pak`) з дескрипторами `.txn` і *дані*
(`paks/TextureData.pak`) з блобами пікселів.

**Чи всього по два?** Так. Master Collection тримає старіший шар дескрипторів у
`stage_data_compressed`, а заміни вищої роздільності — у `PC_TXN_UP`.
Малюється копія з `PC_TXN_UP`, і вона перекриває старіший шар для 98.7%
текстур. Усього в грі 9 973 файли `.txn` у чотирьох шарах.

**Чому відредагована текстура не влазить назад?** Стокова графіка стискається
дуже сильно — 699 КБ можна зберегти в 54 КБ, майже 13:1. Будь-яка правка ламає
довгі повтори, тож стиснений результат більше не влазить у слот. Інструменти
переносять блоб і оновлюють його зсув у змісті.

**Чому правка вийшла зернистою?** Дві пастки: неправильний формат DDS (редактор
ставить DXT5, а текстура може бути DXT1) або відсутність мипів — інструменти
відновлюють і те, і те; і маршрут DDS → правка → DDS перекодовує стиснення
кілька разів. PNG-обмін робить це один раз — використовуй `txn_png.py`.

**Чому правка тексту вилітає?** Майже завжди — короткий екранний напис, що став
довшим. Дивись підказку про довжину вище. Довгі діалоги цієї проблеми не мають.

**Шрифти теж серед текстур?** Так — шрифти це текстури. Є ~20 різних атласів
гліфів, розмножених у 336 копій. `txnup_fonts_strict.py` їх знаходить. Патчити
треба **кожну копію**, а не лише відвідані екрани: непропатчений аркуш — це і є
той `ä´ä°` на екрані замість слова.

**Як гра взагалі малює літеру?** За **сирим байтом**. Шляху через код-поїнт
немає — байт напряму індексує комірку в атласі. Тому алфавітові поза Latin-1
потрібна власна однобайтова кодова сторінка, намальована у вільних комірках.
Уся процедура, пастки й таблиця «що бачу на екрані → яку помилку зробив» — у
**[docs/FONTS.md](docs/FONTS.md)**.

**Перекладений рядок зник повністю — чому?** Одні віджети гра малює бітмапним
атласом, інші — шрифтом TrueType. Однобайтовий рядок, що потрапив у
TrueType-віджет, не є валідним UTF-8, тож двигун відкидає його цілком; якщо
рядок починається з ASCII — виживе лише цей префікс. Зворотна помилка (UTF-8 у
бітмапний віджет) дає один гліф на два байти, з прогалинами.

**То як дізнатись, який рендерер у рядка?** Цього **немає в текстових
файлах** — перевірено чотирма способами, вони перелічені в `docs/FONTS.md`.
Найкращий предиктор — id віджета, але окремі ключі всередині одного віджета
можуть поводитись навпаки, тож потрібен короткий список винятків.

**Чи мипи там, де очікуєш?** Ні. Кеш текстури розрізаний на два `.dlz`:
`<назва>_d.dlz` тримає сам mip 0, а `<назва>.dlz` — решту, тож наївне
склеювання дає ланцюг навпаки. Парувати треба за полем `parent` у шапці
запису — воно каже точно, скільки байтів має йти перед ним. Деталі в
[docs/FORMATS.md](docs/FORMATS.md).

---

## Acknowledgements · Подяки

Thanks to **[otac0n](https://github.com/otac0n)** and the **MGN Community**
for their research into the Metal Gear file formats and the knowledge they
share openly.

Дякуємо **[otac0n](https://github.com/otac0n)** та **спільноті MGN** за
дослідження форматів Metal Gear і знання, якими вони відкрито діляться.

---

## Licence

MIT. See [LICENSE](LICENSE).
