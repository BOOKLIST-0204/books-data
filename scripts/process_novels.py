
import argparse
import json
import re
from pathlib import Path
from uuid import UUID


# ====== 設定 ======

REPO_ROOT = Path(__file__).resolve().parent.parent

MANIFEST_DIR = REPO_ROOT / "staging" / "manifests"
STAGING_DIR = REPO_ROOT / "staging" / "files"
DUPLICATES_DIR = REPO_ROOT / "duplicates"

CATEGORIES = ("BG", "BL")


# ====== 工具 ======

def clean_text(text):
    text = re.sub(r'https?://\S+', '', text)
    text = text.replace("\r\n", "\n")

    lines = [
        re.sub(r'^\s+', '', line).rstrip()
        for line in text.splitlines()
    ]

    result = []
    blank = 0

    for line in lines:
        if line == "":
            blank += 1
            if blank <= 1:
                result.append(line)
        else:
            blank = 0
            result.append(line)

    return "\n".join(result)


def validate_batch_id(batch_id):
    """驗證批次 ID 是否為有效 UUID。"""

    try:
        return str(UUID(batch_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"不合法的 batch ID：{batch_id}")


def validate_file(item):
    """驗證單筆 manifest 資料。"""

    if not isinstance(item, dict):
        raise ValueError("檔案資料格式錯誤")

    new_name = item.get("newName")
    category = item.get("category")
    content_path = item.get("contentPath")

    if not isinstance(new_name, str) or not new_name.strip():
        raise ValueError("缺少有效的新檔名")

    new_name = new_name.strip()

    if new_name.lower().endswith(".txt"):
        new_name = new_name[:-4]

    if (
        not new_name
        or any(char in new_name for char in '<>:"/\\|?*')
        or new_name.endswith((" ", "."))
    ):
        raise ValueError(f"不合法的檔名：{new_name}")

    if category not in CATEGORIES:
        raise ValueError(f"不合法的分類：{category}")

    if not isinstance(content_path, str):
        raise ValueError("缺少 contentPath")

    path = (REPO_ROOT / content_path).resolve()

    # 限制來源只能來自 staging/files
    if not path.is_relative_to(STAGING_DIR.resolve()):
        raise ValueError(f"不允許的檔案路徑：{content_path}")

    if not path.is_file():
        raise FileNotFoundError(f"找不到來源檔案：{content_path}")

    return new_name, category, path


def load_manifest(batch_id):
    """讀取指定批次的 manifest。"""

    manifest_path = MANIFEST_DIR / f"{batch_id}.json"

    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"找不到 manifest：{manifest_path}"
        )

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    if not isinstance(manifest, dict):
        raise ValueError("manifest 格式錯誤")

    if manifest.get("batchId") != batch_id:
        raise ValueError("manifest 的 batchId 與執行參數不一致")

    files = manifest.get("files")

    if not isinstance(files, list):
        raise ValueError("manifest 的 files 必須是陣列")

    if not files:
        raise ValueError("沒有待處理的檔案")

    # 開始處理前，先驗證整批資料
    validated = [validate_file(item) for item in files]

    return manifest_path, validated


def load_env(category):
    target_dir = REPO_ROOT / category
    json_path = REPO_ROOT / f"{category}_Novels.json"

    if not target_dir.is_dir():
        raise FileNotFoundError(f"找不到目標資料夾：{target_dir}")

    if not json_path.is_file():
        raise FileNotFoundError(f"找不到 JSON：{json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        novels = json.load(f)

    if not isinstance(novels, list):
        raise ValueError(f"JSON 格式錯誤：{json_path}")

    return target_dir, json_path, novels


def insert_json(name, json_path, novels_list):
    title, author = (
        name.split("_", 1)
        if "_" in name
        else (name, "")
    )

    item = {
        "title": title,
        "author": author,
        "url": name,
        "desc": "",
        "tags": []
    }

    for i, novel in enumerate(novels_list):
        if not novel.get("tags"):
            novels_list.insert(i, item)
            break
    else:
        novels_list.append(item)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            novels_list,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"💾 JSON 已更新：{name}")


def get_duplicate_path(filename):
    DUPLICATES_DIR.mkdir(parents=True, exist_ok=True)

    dest = DUPLICATES_DIR / filename

    if not dest.exists():
        return dest

    base = Path(filename).stem
    ext = Path(filename).suffix

    count = 1

    while True:
        dest = DUPLICATES_DIR / f"{base}_{count}{ext}"

        if not dest.exists():
            return dest

        count += 1


# ====== 主流程 ======

def main(batch_id):
    batch_id = validate_batch_id(batch_id)

    manifest_path, files = load_manifest(batch_id)

    print(f"📦 批次編號：{batch_id}")
    print(f"📚 共收到 {len(files)} 本小說")

    processed = 0
    duplicated = 0

    for new_name, category, src in files:
        filename = f"{new_name}.txt"

        target_dir, json_path, novels_list = load_env(category)
        dest = target_dir / filename

        # 讀取 UTF-8 文字
        with open(src, "rb") as f:
            content = f.read().decode("utf-8-sig")

        if not content.strip():
            raise ValueError(f"空檔案：{src.name}")

        content = clean_text(content)

        print(f"\n📄 {filename}")
        print(f"📁 分類：{category}")

        # ====== 同名 → duplicates ======

        if dest.exists():
            dup_path = get_duplicate_path(filename)

            dup_path.write_text(content, encoding="utf-8")

            src.unlink()

            duplicated += 1

            print(f"⚠️ 同名 → 已移至 duplicates：{dup_path.name}")
            continue

        # ====== 正常寫入 ======

        dest.write_text(content, encoding="utf-8")

        insert_json(new_name, json_path, novels_list)

        src.unlink()

        processed += 1

        print("✅ 已加入")

    # ====== 清理 manifest ======

    manifest_path.unlink(missing_ok=True)

    print("\n🎉 批次處理完成")
    print(f"正常加入：{processed}")
    print(f"重複檔案：{duplicated}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process novel import batch"
    )

    parser.add_argument(
        "--batch-id",
        required=True,
        help="GitHub Actions workflow batch ID"
    )

    args = parser.parse_args()

    main(args.batch_id)
