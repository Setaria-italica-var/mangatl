# M0锛氬彲杩愯鐨勯鏋朵笌 Spike 璁″垝

> 鐩爣锛氬湪涓嶄緷璧?GUI銆佷笉鎺ョ炕璇戙€佷笉鎺ョ湡瀹炴ā鍨嬬殑鍓嶆彁涓嬶紝鎶娿€岃浇鍏?鈫?妫€娴?鈫?OCR 鈫?鎶瑰瓧銆嶈繖鏉￠摼璺窇閫氾紝
> 骞跺缓绔嬪彲鍥炲綊鐨勬牱鏈泦銆侻0 缁撴潫鏃讹紝鍓╀笅鐨勫伐浣滃彧鏄妸涓変釜閫傞厤鍣ㄦ崲鎴愮湡妯″瀷銆?
## 1. 鑼冨洿

**鍋?*

- 椤圭洰鐘舵€侊紙`project.json`锛岄樁娈典綅鎺╃爜锛屾柇鐐圭画璺戯級
- 涓変釜閫傞厤鍣ㄥ崗璁紙Detector / Ocr / Inpainter锛変笌娉ㄥ唽琛?- 缂栨帓鏈嶅姟锛堥€愰〉鎵ц銆佸崟椤靛け璐ラ殧绂汇€佹瘡椤佃惤鐩橈級
- CLI锛坄python -m mangatl run <dir>`锛?- 绂荤嚎 stub锛堟棤 torch / 鏃?numpy / 鏃犵綉缁滀篃鑳借窇閫氾級
- 绔埌绔祴璇?
**涓嶅仛**锛堢暀缁?M1/M2锛?
- 鐪熷疄妯″瀷鎺ㄧ悊銆佹ā鍨嬩笅杞?- 缈昏瘧銆佹帓鐗堛€佹覆鏌?- GUI銆佹墦鍖?
## 2. 宸蹭氦浠?
```
src/mangatl/
  domain/block.py        TextBlock锛坆box/text/translation/confidence/vertical/lines锛?  domain/project.py      Page / Project锛屽師瀛愬啓 project.json
  adapters/base.py       Detector / Ocr / Inpainter 鍗忚 + Registry
  adapters/stubs.py      GridDetector / EchoOcr / CopyInpainter
  core/config.py         RunConfig锛堜笉鍙彉锛? resolve()
  core/pipeline.py       PipelineService / Event / RunSummary
  cli/main.py            argparse 鍏ュ彛
  __main__.py            python -m mangatl
tests/test_pipeline_stub.py   7 涓敤渚嬶細鍏ㄩ樁娈点€佽烦杩囥€乫orce銆佸潖椤甸殧绂汇€佺己鐩綍銆侀潪娉曢樁娈点€佷簨浠?docs/m0-plan.md        鏈枃浠?```

## 3. 鎬庝箞璺?
```bat
cd /d C:\Users\admin\Documents\deepseek-harness\default-workspace\mangatl
.venv\Scripts\activate.bat

:: 绔埌绔紙stub锛屽嚑绉掑畬鎴愶級
python -m mangatl run .\samples\vol1

:: 娴嬭瘯涓庨潤鎬佹鏌?python -m pytest -q
python -m ruff check .
```

`<dir>` 閲屾斁鍥剧墖鍗冲彲锛涢娆¤繍琛屼細鎵洰褰曞苟鐢熸垚 `project.json`銆備骇鐗╁啓鍒?`<dir>\inpainted\`銆?
**棰勬湡**锛氭瘡椤垫墦鍗?`[001.png] done: N blocks`锛屾渶鍚庝竴琛屾槸 JSON 姹囨€?`{"total": 2, "ok": 2, "failed": 0, "skipped": 0, "blocks": 8}`銆?
**鏂偣**锛氬啀娆¤繍琛屼細璺宠繃宸插畬鎴愰樁娈碉紙涓嶄骇鐢熶簨浠讹級锛沗--force` 寮哄埗閲嶈窇銆?
## 4. 鏍锋湰闆嗭紙M0 鐨勯獙鏀舵潗鏂欙級

鍑嗗 10 椤碉紝鏀惧埌 `samples/`锛堜笉杩涚増鏈簱锛夛細

| 缂栧彿 | 绫诲瀷 | 鐢ㄩ€?|
|---|---|---|
| 01鈥?4 | 榛戠櫧鏃ユ极锛?*绔栨帓**涓轰富锛堝崟鍒?/ 澶氬垪 / 甯︽爣鐐?/ 甯︽暟瀛楋級 | 绔栨帓妫€娴嬩笌 OCR |
| 05鈥?6 | 榛戠櫧鏃ユ极锛屾í鎺掑璇?| 甯歌璺緞 |
| 07鈥?8 | 褰╄壊鏉℃极锛堥暱鍥惧垏鐗囷級 | 鎺ョ紳涓庡僵鑹茶儗鏅?|
| 09鈥?0 | 鑻辨枃瀵圭櫧 | 鑻辨枃 OCR 璺敱 |

## 5. 楠屾敹鎸囨爣

| 椤?| 鐩爣 | 娴嬫硶 |
|---|---|---|
| 绔埌绔彲璺?| 10 椤垫棤宕╂簝 | `mangatl run` 閫€鍑虹爜 0 |
| 鏂偣缁窇 | 浜屾杩愯 0 浜嬩欢 | 鐪嬭緭鍑?|
| 鍗曢〉鑰楁椂 | 鈮?10 s锛? GB GPU锛?| 閫愰〉璁℃椂 |
| 鏄惧瓨宄板€?| 鈮?5.5 GB | `nvidia-smi` 閲囨牱 |
| 妫€娴嬪彫鍥?| 鈮?95% | 浜哄伐鏍囨敞 10 椤电殑妗嗘暟瀵规瘮 |
| 鎺╄啘骞插噣搴?| 鏄庢樉娈嬬暀 鈮?10% 椤?| 鐪?`inpainted/` |
| 绔栨帓 OCR | 瀛楃鍑嗙‘鐜?鈮?90% | 浜哄伐姣斿 4 椤电珫鎺?|

## 6. 涓嬩竴姝ワ細鎺ョ湡妯″瀷锛圡0.5锛?
鎸変緷璧栦粠灏戝埌澶氭帹杩涳紝姣忔閮藉彲鐙珛楠岃瘉锛?
1. **Inpainter 鈫?LaMa**锛氬彧渚濊禆 torch + numpy + opencv锛涘厛鍋氥€岀函鑹插揩璺緞 + LaMa銆嶄袱鏉″垎鏀€?2. **Detector 鈫?CTD**锛歵orch + 妯″瀷鏉冮噸锛屼骇鍑?bbox / lines / mask銆?3. **OCR 鈫?manga-ocr锛堟棩锛? PP-OCR锛堣嫳锛?*锛歰nnxruntime 鎴?torch銆?
妯″瀷鏉冮噸锛堢害 1.2 GB锛変紭鍏堣蛋 `hf-mirror.com`锛涗笅杞芥竻鍗曞啓杩?`data/models/manifest.json`锛堣
[portable-data-contract.md](portable-data-contract.md)锛夈€?
渚濊禆瀹夎绀轰緥锛?
```bat
uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cu124
uv pip install --python .venv\Scripts\python.exe numpy opencv-python-headless pillow onnxruntime
```

## 7. 椋庨櫓

| 椋庨櫓 | 澶勭疆 |
|---|---|
| 妯″瀷涓嬭浇琚 | `hf-mirror.com` + 鏂偣缁紶锛涙潈閲嶆牎楠?sha256 |
| 8 GB 鏄惧瓨涓嶅 | LaMa 1024 甯搁┗ + 鎵归噺鍗歌浇锛汷OM 闄?512 |
| 绔栨帓 OCR 宸?| manga-ocr 浼樺厛锛涜鍥涜竟褰㈤€忚鐭鍚庡啀璇嗗埆 |
| 鐪熷疄鍥剧墖鏍煎紡澶氭牱 | 杞藉叆灞傜粺涓€杞?RGB锛屼繚鐣?alpha 閫氶亾鏍囪 |
| 娴嬭瘯渚濊禆鐪熷疄妯″瀷 | 淇濇寔 stub 璺緞姘歌繙鍙窇锛孋I 鍙窇 stub |
