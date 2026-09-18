"""GIMP-side batch script (runs INSIDE GIMP via python-fu-eval).

Must stay Python 2/3 polyglot: GIMP 2.10 bundles Python 2, GIMP 3 bundles
Python 3. Rules: no f-strings, no keyword-only args, no ``open(...,
encoding=)``, ``print()`` only via sys.stdout.write.

Contract (all via the XCF_GIT_SYNC_JOB env var pointing at a JSON file):
  job = {"xcf": <path>, "staging": <dir>, "flattened": <bool>}

Stdout manifest (parent parses this; all other lines ignored):
  XCFGSYNC-GIMP\\t<version>
  XCFGSYNC-EXPORT\\t<staging png path>\\t<0|1 visible>\\t<json [group..., name]>
  XCFGSYNC-FLAT\\t<staging png path>
  XCFGSYNC-ERROR\\t<where>\\t<message>
"""

FU_SOURCE = '''
import json
import os
import sys
import traceback


def _log(msg):
    sys.stdout.write(str(msg) + "\\n")
    sys.stdout.flush()


def _is_group(layer):
    try:
        return bool(pdb.gimp_item_is_group(layer))
    except Exception:
        return getattr(layer, "children", None) is not None


def _children(group):
    kids = getattr(group, "children", None)
    if kids is not None:
        return list(kids)
    res = pdb.gimp_item_get_children(group)
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], int):
        return list(res[1])
    return list(res)


def _walk(image):
    stack = [(list(image.layers), [])]
    while stack:
        siblings, prefix = stack.pop()
        for layer in siblings:
            if _is_group(layer):
                stack.append((_children(layer), prefix + [layer.name]))
            else:
                yield (prefix, layer)


def _export_layer(image, layer, out_path):
    base = pdb.gimp_image_base_type(image)
    new_image = pdb.gimp_image_new(int(layer.width), int(layer.height), base)
    try:
        new_layer = pdb.gimp_layer_new_from_drawable(layer, new_image)
        pdb.gimp_image_insert_layer(new_image, new_layer, None, 0)
        try:
            pdb.gimp_layer_set_offsets(new_layer, 0, 0)
        except Exception:
            pass
        if pdb.gimp_image_base_type(new_image) == 2:  # INDEXED
            pdb.gimp_image_convert_rgb(new_image)
        # NOTE: save the layer directly, no flatten -- flatten fills
        # transparency with the background color and drops the alpha channel.
        try:
            pdb.gimp_file_save(new_image, new_layer, out_path, out_path)
        except TypeError:
            pdb.gimp_file_save(0, new_image, new_layer, out_path, out_path)
    finally:
        try:
            pdb.gimp_image_delete(new_image)
        except Exception:
            pass


def _export_flattened(image, flat_path):
    dup = pdb.gimp_image_duplicate(image)
    try:
        # merge_visible (not flatten) preserves the alpha channel.
        merged = pdb.gimp_image_merge_visible_layers(dup, 0)
        try:
            pdb.gimp_file_save(dup, merged, flat_path, flat_path)
        except TypeError:
            pdb.gimp_file_save(0, dup, merged, flat_path, flat_path)
    finally:
        try:
            pdb.gimp_image_delete(dup)
        except Exception:
            pass


def main():
    try:
        RUN_NONINTERACTIVE
    except NameError:
        RUN_NONINTERACTIVE = 0
    job_path = os.environ.get("XCF_GIT_SYNC_JOB", "")
    with open(job_path, "rb") as fh:
        job = json.loads(fh.read().decode("utf-8"))
    xcf_path = job["xcf"]
    staging = job["staging"]
    want_flat = job.get("flattened", True)

    try:
        _log("XCFGSYNC-GIMP\\t" + str(pdb.gimp_version()))
    except Exception:
        pass

    image = pdb.gimp_file_load(xcf_path, xcf_path)
    try:
        idx = 0
        for group_path, layer in _walk(image):
            out_path = os.path.join(staging, "%04d.png" % idx)
            idx += 1
            try:
                visible = 1 if layer.visible else 0
            except Exception:
                visible = 1
            try:
                _export_layer(image, layer, out_path)
                meta = json.dumps(list(group_path) + [layer.name])
                _log("XCFGSYNC-EXPORT\\t" + out_path + "\\t" + str(visible) + "\\t" + meta)
            except Exception:
                _log("XCFGSYNC-ERROR\\t" + str(getattr(layer, "name", "?"))
                     + "\\t" + traceback.format_exc(limit=3).replace("\\n", " | "))
        if want_flat:
            try:
                flat_path = os.path.join(staging, "_flattened.png")
                _export_flattened(image, flat_path)
                _log("XCFGSYNC-FLAT\\t" + flat_path)
            except Exception:
                _log("XCFGSYNC-ERROR\\t_flattened\\t" + traceback.format_exc(limit=3).replace("\\n", " | "))
    finally:
        try:
            pdb.gimp_image_delete(image)
        except Exception:
            pass


_code = 0
try:
    main()
except Exception:
    _log("XCFGSYNC-ERROR\\tjob\\t" + traceback.format_exc(limit=5).replace("\\n", " | "))
    _code = 1
finally:
    sys.stdout.flush()
    try:
        pdb.gimp_quit(_code)
    except Exception:
        pass
    import os as _os
    _os._exit(_code)
'''


def get_fu_source():
    """Return the GIMP-side script text."""
    return FU_SOURCE
