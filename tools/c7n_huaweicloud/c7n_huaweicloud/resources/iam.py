import functools
import logging
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkiam.v3 import UpdateLoginProtectRequest, UpdateLoginProjectReq, UpdateLoginProject

from c7n.filters import ValueFilter
from c7n.utils import type_schema, chunks
from tools.c7n_huaweicloud.c7n_huaweicloud.actions import HuaweiCloudBaseAction
from tools.c7n_huaweicloud.c7n_huaweicloud.provider import resources
from tools.c7n_huaweicloud.c7n_huaweicloud.query import QueryResourceManager, TypeInfo

log = logging.getLogger("custodian.huaweicloud.resources.volume")

@resources.register('iam-user')
class User(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'iam5'
        enum_spec = ("list_users_v5", 'Users', 'marker_limit')
        id = 'id'
        tag = True

@User.action_registry.register("set-login-protect")
class SetLoginProtect(HuaweiCloudBaseAction):
    """Set IAMUser Login Protect.

    :Example:

    .. code-block:: yaml

        policies:
          - name: set-User-login-protect
            resource: huaweicloud.IAM-User
            flters:
              - type: value
                key: metadata.__system__encrypted
                value: "0"
            actions:
              - type: set-login-protect
                enabled: true
                verification_method: vmfa
    """

    schema = type_schema(
        'set-login-protect',
        enabled={'type': 'boolean'},
        verification_method={'enum': ['vmfa', 'sms', 'email']},
    )

    def perform_action(self, resource):
        client = self.manager.get_client()
        try:
            request = UpdateLoginProtectRequest(user_id=resource["id"])

            loginProtectBody = UpdateLoginProject(
                enabled=self.data.get('enabled'),
                verification_method=self.data.get('verification_method')
            )
            request.body = UpdateLoginProjectReq(login_protect=loginProtectBody)

            response = client.update_login_protect(request)
            print(response)
        except exceptions.ClientRequestException as e:
            print(e.status_code)
            print(e.request_id)
            print(e.error_code)
            print(e.error_msg)

@User.filter_registry.register('access-key')
class UserAccessKey(ValueFilter):
    """Filter IAM users based on access-key values

    By default multiple uses of this filter will match
    on any user key satisfying either filter. To find
    specific keys that match multiple access-key filters,
    use `match-operator: and`

    :example:

    .. code-block:: yaml

        policies:
          - name: iam-users-with-active-keys
            resource: iam-user
            filters:
              - type: access-key
                key: status
                value: active
              - type: access-key
                match-operator: and
                key: create_time
                value_type: age
                value: 90
    """

    schema = type_schema(
        'access-key',
        rinherit=ValueFilter.schema,
        **{'match-operator': {'enum': ['and', 'or']}})
    schema_alias = False
    permissions = ('iam:ListAccessKeys',)
    annotation_key = 'c7n:AccessKeys'
    matched_annotation_key = 'c7n:matched-keys'
    annotate = False

    def get_user_keys(self, client, user_set):
        for u in user_set:
            u[self.annotation_key] = self.manager.retry(
                client.list_access_keys_v5,
                user_id=u['userId'])['access_keys']

    def process(self, resources, event=None):
        client = self.manager.get_client()
        with self.executor_factory(max_workers=2) as w:
            augment_set = [r for r in resources if self.annotation_key not in r]
            self.log.debug(
                "Querying %d users' api keys" % len(augment_set))
            list(w.map(
                functools.partial(self.get_user_keys, client),
                chunks(augment_set, 50)))

        matched = []
        match_op = self.data.get('match-operator', 'or')
        for r in resources:
            keys = r[self.annotation_key]
            if self.matched_annotation_key in r and match_op == 'and':
                keys = r[self.matched_annotation_key]
            k_matched = []
            for k in keys:
                if self.match(k):
                    k_matched.append(k)
            for k in k_matched:
                k['c7n:match-type'] = 'access'
            self.merge_annotation(r, self.matched_annotation_key, k_matched)
            if k_matched:
                matched.append(r)
        return matched