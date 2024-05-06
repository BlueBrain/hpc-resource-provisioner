import json

from .pcluster_manager import (
    InvalidRequest,
    PClusterError,
    pcluster_create,
    pcluster_delete,
    pcluster_describe,
)


def pcluster_handler(event, _context=None):
    """
    * Check whether we have a GET, a POST or a DELETE method
    * Pass on to pcluster_*_handler
    """
    if event.get("httpMethod"):
        if event["httpMethod"] == "GET":
            return pcluster_describe_handler(event, _context)
        elif event["httpMethod"] == "POST":
            return pcluster_create_handler(event, _context)
        elif event["httpMethod"] == "DELETE":
            return pcluster_delete_handler(event, _context)
        else:
            return response_text(f"{event['httpMethod']} not supported", code=400)

    return response_text(
        "Could not determine HTTP method - make sure to GET, POST or DELETE", code=400
    )


def pcluster_create_handler(event, _context=None):
    """Request the creation of an HPC cluster for a given vlab_id"""
    try:
        vlab_id, options = _get_vlab_query_params(event)
        pc_output = pcluster_create(vlab_id, options)
    except InvalidRequest as e:
        return response_text(str(e), code=400)
    except PClusterError as e:
        return {"statusCode": 403, "body": str(e)}
    except Exception as e:
        return {"statusCode": 500, "body": str(e)}

    return response_json(pc_output)


def pcluster_describe_handler(event, _context=None):
    """Describe a cluster given the vlab_id"""
    vlab_id, _ = _get_vlab_query_params(event)

    try:
        pc_output = pcluster_describe(vlab_id)
    except Exception as e:
        return {"statusCode": 500, "body": str(e)}

    return response_json(pc_output)


def pcluster_delete_handler(event, _context=None):
    vlab_id, _ = _get_vlab_query_params(event)

    try:
        pc_output = pcluster_delete(vlab_id)
    except Exception as e:
        return {"statusCode": 500, "body": str(e)}

    return response_json(pc_output)


def _get_vlab_query_params(event):
    vlab_id = event.get("vlab_id")
    options = {}

    if vlab_id is None and "queryStringParameters" in event:
        if options := event.get("queryStringParameters"):
            vlab_id = options.pop("vlab_id", None)

    if vlab_id is None:
        raise InvalidRequest("missing required 'vlab_id' query param")

    return vlab_id, options


def response_text(text: str, code: int = 200):
    return {"statusCode": code, "body": text}


def response_json(data: dict, code: int = 200):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data),
    }
