import json
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from assistant.provider_security import SecretProtectionError
from assistant.views import api
from .services import configure, disable, configuration_status


def _unique_pairs(pairs):
    data = {}
    for name, value in pairs:
        if name in data:
            raise ValueError()
        data[name] = value
    return data


@sensitive_post_parameters('api_key')
@sensitive_variables('data', 'raw')
@api(['GET', 'POST', 'DELETE'])
def config(request):
    if request.method == 'GET':
        return JsonResponse(configuration_status(request.user))
    if request.method == 'DELETE':
        return JsonResponse(disable(request.user))
    try:
        raw = request.body
    except Exception:
        return JsonResponse({'error': 'invalid_configuration', 'detail': '配置请求无法读取，未进行 AI 调用。'}, status=400)
    if request.content_type != 'application/json' or len(raw) > 4096:
        raise ValidationError('请使用受限 JSON 配置表单。')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise ValidationError('配置内容无效。') from None
    if data == {'action': 'disable'} or (isinstance(data, dict) and set(data) == {'enable'} and data['enable'] is False):
        return JsonResponse(disable(request.user))
    try:
        return JsonResponse(configure(request.user, data))
    except ValidationError:
        raise
    except (SecretProtectionError, OSError):
        return JsonResponse({'error': 'key_storage_failed', 'detail': '本次密钥无法安全保存，请检查本机配置状态；没有进行 AI 调用。'}, status=400)
    except Exception:
        # Never emit a debug traceback, DB exception, ciphertext, URL or key.
        return JsonResponse({'error': 'configuration_failed', 'detail': '本次配置结果未确认，请刷新本机状态并检查私有存储及数据库；没有进行 AI 调用。'}, status=400)
