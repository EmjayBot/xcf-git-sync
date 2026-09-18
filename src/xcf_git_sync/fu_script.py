"""GIMP-side batch script (runs INSIDE GIMP via python-fu-eval).

Must stay Python 2/3 polyglot: GIMP 2.10 bundles Python 2 (``pdb`` is
predefined, classic ``pdb.*`` calls), GIMP 3 bundles Python 3 (no ``pdb``
or ``gimpfu``; use ``gi.repository.Gimp``). The engine is detected at
runtime. New code must parse under Python 2 grammar: no f-strings,
no keyword-only args, no ``open(..., encoding=)``.

Contract (XCF_GIT_SYNC_JOB env var -> JSON file):
  job = {"xcf": <path>, "staging": <dir>, "flattened": <bool>,
         "mode": "export" | "list"}

Stdout manifest (parent parses; all other lines ignored):
  XCFGSYNC-GIMP\\t<version>
  XCFGSYNC-LAYER\\t<0|1 visible>\\t<json [group..., name]>      (list mode)
  XCFGSYNC-EXPORT\\t<staging png>\\t<0|1>\\t<json [group..., name]>
  XCFGSYNC-FLAT\\t<staging png>
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


def _load_job():
    job_path = os.environ.get("XCF_GIT_SYNC_JOB", "")
    fh = open(job_path, "rb")
    try:
        return json.loads(fh.read().decode("utf-8"))
    finally:
        fh.close()


def _detect_engine():
    try:
        pdb
        return "gimp2"
    except NameError:
        return "gimp3"


# ---------------------------------------------------------------- gimp2 --
def _g2_children(group):
    kids = getattr(group, "children", None)
    if kids is not None:
        return list(kids)
    res = pdb.gimp_item_get_children(group)
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], int):
        return list(res[1])
    return list(res)


def _g2_is_group(layer):
    try:
        return bool(pdb.gimp_item_is_group(layer))
    except Exception:
        return getattr(layer, "children", None) is not None


def _g2_walk(image):
    stack = [(list(image.layers), [])]
    while stack:
        siblings, prefix = stack.pop()
        for layer in siblings:
            if _g2_is_group(layer):
                stack.append((_g2_children(layer), prefix + [layer.name]))
            else:
                try:
                    visible = bool(layer.visible)
                except Exception:
                    visible = True
                yield (prefix, layer.name, visible, layer)


def _g2_export_layer(image, layer, out_path):
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
        # Save the layer directly (no flatten: flatten fills transparency
        # with the background color and drops the alpha channel).
        try:
            pdb.gimp_file_save(new_image, new_layer, out_path, out_path)
        except TypeError:
            pdb.gimp_file_save(0, new_image, new_layer, out_path, out_path)
    finally:
        try:
            pdb.gimp_image_delete(new_image)
        except Exception:
            pass


def _g2_export_flattened(image, flat_path):
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


def _run_gimp2(job):
    try:
        RUN_NONINTERACTIVE
    except NameError:
        RUN_NONINTERACTIVE = 0
    try:
        _log("XCFGSYNC-GIMP\\t" + str(pdb.gimp_version()))
    except Exception:
        pass
    staging = job.get("staging", "")
    mode = job.get("mode", "export")
    image = pdb.gimp_file_load(job["xcf"], job["xcf"])
    try:
        idx = 0
        for group_path, name, visible, layer in _g2_walk(image):
            if mode == "list":
                meta = json.dumps(list(group_path) + [name])
                _log("XCFGSYNC-LAYER\\t" + str(1 if visible else 0) + "\\t" + meta)
                continue
            out_path = os.path.join(staging, "%04d.png" % idx)
            idx += 1
            try:
                _g2_export_layer(image, layer, out_path)
                meta = json.dumps(list(group_path) + [name])
                _log("XCFGSYNC-EXPORT\\t" + out_path + "\\t"
                     + str(1 if visible else 0) + "\\t" + meta)
            except Exception:
                _log("XCFGSYNC-ERROR\\t" + str(name) + "\\t"
                     + traceback.format_exc(limit=3).replace("\\n", " | "))
        if mode == "export" and job.get("flattened", True):
            try:
                flat_path = os.path.join(staging, "_flattened.png")
                _g2_export_flattened(image, flat_path)
                _log("XCFGSYNC-FLAT\\t" + flat_path)
            except Exception:
                _log("XCFGSYNC-ERROR\\t_flattened\\t"
                     + traceback.format_exc(limit=3).replace("\\n", " | "))
    finally:
        try:
            pdb.gimp_image_delete(image)
        except Exception:
            pass


# ---------------------------------------------------------------- gimp3 --
def _g3_pdb():
    from gi.repository import Gimp
    return Gimp.get_pdb()


def _g3_run_proc(pdb, name, props):
    proc = pdb.lookup_procedure(name)
    cfg = proc.create_config()
    for key, value in props.items():
        cfg.set_property(key, value)
    return proc.run(cfg)


def _g3_walk(image):
    stack = [(list(image.get_layers()), [])]
    while stack:
        siblings, prefix = stack.pop()
        for layer in siblings:
            try:
                grp = bool(layer.is_group())
            except Exception:
                grp = False
            if grp:
                try:
                    sub = list(layer.get_children())
                except Exception:
                    sub = []
                stack.append((sub, prefix + [layer.get_name()]))
            else:
                try:
                    visible = bool(layer.get_visible())
                except Exception:
                    visible = True
                yield (prefix, layer.get_name(), visible, layer)


def _g3_export_layer(pdb, image, layer, out_path):
    from gi.repository import Gimp
    base = image.get_base_type()
    new_image = Gimp.Image.new(layer.get_width(), layer.get_height(), base)
    try:
        res = _g3_run_proc(pdb, "gimp-layer-new-from-drawable",
                           {"drawable": layer, "dest-image": new_image})
        new_layer = res.index(1)
        _g3_run_proc(pdb, "gimp-image-insert-layer",
                     {"image": new_image, "layer": new_layer, "position": 0})
        try:
            _g3_run_proc(pdb, "gimp-layer-set-offsets",
                         {"layer": new_layer, "offx": 0, "offy": 0})
        except Exception:
            pass
        if int(new_image.get_base_type()) == int(Gimp.ImageBaseType.INDEXED):
            _g3_run_proc(pdb, "gimp-image-convert-rgb", {"image": new_image})
        # Save the layer directly (no flatten: keeps the alpha channel).
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, new_image,
                       _g3_gio_file(out_path), None)
    finally:
        try:
            _g3_run_proc(pdb, "gimp-image-delete", {"image": new_image})
        except Exception:
            pass


def _g3_gio_file(path):
    from gi.repository import Gio
    return Gio.File.new_for_path(path)


def _g3_export_flattened(pdb, image, flat_path):
    from gi.repository import Gimp
    dup = image.duplicate()
    try:
        # merge_visible (not flatten) preserves the alpha channel.
        dup.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        from gi.repository import Gio
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup,
                       Gio.File.new_for_path(flat_path), None)
    finally:
        try:
            _g3_run_proc(pdb, "gimp-image-delete", {"image": dup})
        except Exception:
            pass


def _run_gimp3(job):
    from gi.repository import Gimp
    pdb = _g3_pdb()
    try:
        _log("XCFGSYNC-GIMP\\t" + str(Gimp.version()))
    except Exception:
        pass
    staging = job.get("staging", "")
    mode = job.get("mode", "export")
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                           _g3_gio_file(job["xcf"]))
    try:
        idx = 0
        for group_path, name, visible, layer in _g3_walk(image):
            if mode == "list":
                meta = json.dumps(list(group_path) + [name])
                _log("XCFGSYNC-LAYER\\t" + str(1 if visible else 0) + "\\t" + meta)
                continue
            out_path = os.path.join(staging, "%04d.png" % idx)
            idx += 1
            try:
                _g3_export_layer(pdb, image, layer, out_path)
                meta = json.dumps(list(group_path) + [name])
                _log("XCFGSYNC-EXPORT\\t" + out_path + "\\t"
                     + str(1 if visible else 0) + "\\t" + meta)
            except Exception:
                _log("XCFGSYNC-ERROR\\t" + str(name) + "\\t"
                     + traceback.format_exc(limit=3).replace("\\n", " | "))
        if mode == "export" and job.get("flattened", True):
            try:
                flat_path = os.path.join(staging, "_flattened.png")
                _g3_export_flattened(pdb, image, flat_path)
                _log("XCFGSYNC-FLAT\\t" + flat_path)
            except Exception:
                _log("XCFGSYNC-ERROR\\t_flattened\\t"
                     + traceback.format_exc(limit=3).replace("\\n", " | "))
    finally:
        pass  # image is released with the batch process


def _quit(engine, code):
    if engine == "gimp2":
        try:
            pdb.gimp_quit(code)
        except Exception:
            pass
        import os as _os
        _os._exit(code)
    # GIMP 3: clean quit via the PDB (os._exit would only kill the
    # plug-in host and leave the main process hanging).
    try:
        pdb3 = _g3_pdb()
        _g3_run_proc(pdb3, "gimp-quit", {"force": True})
    except Exception:
        pass
    import os as _os2
    _os2._exit(code if code else 0)


_code = 0
_engine = _detect_engine()
try:
    _job = _load_job()
    if _engine == "gimp2":
        _run_gimp2(_job)
    else:
        _run_gimp3(_job)
except Exception:
    _log("XCFGSYNC-ERROR\\tjob\\t" + traceback.format_exc(limit=5).replace("\\n", " | "))
    _code = 1
finally:
    sys.stdout.flush()
    _quit(_engine, _code)
'''


def get_fu_source():
    """Return the GIMP-side script text."""
    return FU_SOURCE
