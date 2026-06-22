"""Portal/hosted feature layer publishing helpers."""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile

from .arcpy_tools import arcpy_messages, fail_arcpy

LOGGER = logging.getLogger(__name__)


def try_find_owned_feature_service(service_name: str) -> str | None:
    """Return a portal item id if ArcGIS API for Python can find the service.

    This is a best-effort preflight. Some organizations have item titles that
    differ from service names, so the publisher still remains the source of
    truth during upload.
    """

    try:
        from arcgis.gis import GIS  # type: ignore[import-not-found]

        gis = GIS("pro")
        user = gis.users.me
        if not user:
            return None
        query = f'title:"{service_name}" AND owner:{user.username}'
        items = gis.content.search(query=query, item_type="Feature Service", max_items=10)
        for item in items:
            if item.title == service_name:
                return item.id
        return items[0].id if items else None
    except Exception:
        return None


def overwrite_online(arcpy, fc: str, args) -> None:
    """Overwrite a hosted feature layer using an ArcGIS Pro sharing draft."""

    item_id = try_find_owned_feature_service(args.service_name)
    if item_id:
        LOGGER.info("Found likely hosted feature service item before overwrite: %s", item_id)
    else:
        LOGGER.warning(
            "Could not confirm the hosted service with ArcGIS API preflight. "
            "Continuing because ArcPy upload will report the authoritative result."
        )

    layer = None
    try:
        aprx = arcpy.mp.ArcGISProject(args.aprx)
        maps = aprx.listMaps(args.map_name)
        map_obj = maps[0] if maps else aprx.createMap(args.map_name)
        layer = map_obj.addDataFromPath(fc)
        layer.name = args.layer_name or Path(fc).name
        with tempfile.TemporaryDirectory() as tmp:
            draft_file = Path(tmp) / f"{args.service_name}.sddraft"
            sd_file = Path(tmp) / f"{args.service_name}.sd"
            draft = map_obj.getWebLayerSharingDraft("HOSTING_SERVER", "FEATURE", args.service_name, [layer])
            draft.overwriteExistingService = True
            draft.copyDataToServer = True
            draft.summary = args.summary
            draft.tags = args.tags
            if args.portal_folder:
                draft.portalFolder = args.portal_folder
            draft.exportToSDDraft(str(draft_file))
            arcpy.server.StageService(str(draft_file), str(sd_file))
            arcpy.server.UploadServiceDefinition(str(sd_file), "HOSTING_SERVER")
    except Exception as exc:  # pragma: no cover - requires ArcGIS Pro
        fail_arcpy(arcpy, f"Could not overwrite hosted service: {args.service_name}", exc)
    finally:
        if layer is not None:
            try:
                map_obj.removeLayer(layer)
            except Exception:
                LOGGER.debug("Could not remove temporary publishing layer. ArcGIS messages: %s", arcpy_messages(arcpy, 1))
