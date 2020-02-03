""" Python SDK for JupiterOne GraphQL API """
# pylint: disable=W0212,no-name-in-module
# see https://github.com/PyCQA/pylint/issues/409

import json
from typing import Dict, List

import requests
from retrying import retry

from jupiterone.errors import (
    JupiterOneClientError,
    JupiterOneApiRetryError,
    JupiterOneApiError
)

from jupiterone.constants import (
    J1QL_SKIP_COUNT,
    J1QL_LIMIT_COUNT,
    QUERY_V1,
    CREATE_ENTITY,
    DELETE_ENTITY,
    CREATE_RELATIONSHIP,
    DELETE_RELATIONSHIP
)

def retry_on_429(exc):
    """ Used to trigger retry on rate limit """
    return isinstance(exc, JupiterOneApiRetryError)


class JupiterOneClient:
    """ Python client class for the JupiterOne GraphQL API """
    # pylint: disable=too-many-instance-attributes

    DEFAULT_URL = 'https://api.us.jupiterone.io'

    RETRY_OPTS = {
        'wait_exponential_multiplier': 1000,
        'wait_exponential_max': 10000,
        'stop_max_delay': 300000,
        'retry_on_exception': retry_on_429
    }

    def __init__(self, account: str = None, token: str = None, url: str = DEFAULT_URL):
        self.account = account
        self.token = token
        self.url = url
        self.query_endpoint = self.url + '/graphql'
        self.rules_endpoint = self.url + '/rules/graphql'
        self.headers = {
            'Authorization': 'Bearer {}'.format(self.token),
            'LifeOmic-Account': self.account
        }

    @property
    def account(self):
        """ Your JupiterOne account ID """
        return self._account

    @account.setter
    def account(self, value: str):
        """ Your JupiterOne account ID """
        if not value:
            raise JupiterOneClientError('account is required')
        self._account = value

    @property
    def token(self):
        """ Your JupiteOne access token """
        return self._token

    @token.setter
    def token(self, value: str):
        """ Your JupiteOne access token """
        if not value:
            raise JupiterOneClientError('token is required')
        self._token = value

    # pylint: disable=R1710
    @retry(**RETRY_OPTS)
    def _execute_query(self, query: str, **kwargs) -> Dict:
        """ Executes query against graphql endpoint """
        variables: Dict = kwargs.pop('variables', None)
        include_deleted: bool = kwargs.pop('include_deleted', False)
        dry_run: bool = kwargs.pop('dry_run', False)

        data = dict(
            query=query,
            dryRun=dry_run,
            includeDeleted=include_deleted
        )

        if variables:
            data.update(variables=variables)

        response = requests.post(self.query_endpoint, headers=self.headers, json=data)

        if response.status_code == 200:
            if response._content:
                content = json.loads(response._content)
                if 'errors' in content:
                    raise JupiterOneApiError(content.get('errors'))
                return response.json()

        elif response.status_code in [429, 500]:
            raise JupiterOneApiRetryError('JupiterOne API rate limit exceeded')

        else:
            content = json.loads(response._content)
            raise JupiterOneApiError('{}:{}'.format(response.status_code, content.get('error')))

    def query_v1(self, query: str, **kwargs) -> Dict:
        """ Performs a V1 graph query
            args:
                query (str): Query text
                skip (int):  Skip entity count
                limit (int): Limit entity count
                include_deleted (bool): Include recently deleted entities in query/search
                dry_run (bool): Execute in dry run mode
        """
        skip: int = kwargs.pop('skip', J1QL_SKIP_COUNT)
        limit: int = kwargs.pop('limit', J1QL_LIMIT_COUNT)
        include_deleted: bool = kwargs.pop('include_deleted', False)
        dry_run: bool = kwargs.pop('dry_run', False)

        results: List = []
        page: int = 0

        while True:
            variables = {'query': f"{query} SKIP {page * skip} LIMIT {limit}"}
            response = self._execute_query(
                query=QUERY_V1,
                variables=variables,
                include_deleted=include_deleted,
                dry_run=dry_run
            )

            data = response['data']['queryV1']['data']

            # If tree query then no pagination
            if 'vertices' in data and 'edges' in data:
                return data

            if len(data) < J1QL_SKIP_COUNT:
                results.extend(data)
                break

            results.extend(data)
            page += 1

        return {'data': results}

    def create_entity(self, **kwargs) -> Dict:
        """ Creates an entity in graph.  It will also update an existing entity.

        args:
            entity_key (str): Unique key for the entity
            entity_type (str): Value for _type of entity
            entity_class (str): Value for _class of entity
            timestamp (int): Specify createdOn timestamp
            properties (dict): Dictionary of key/value entity properties
            dry_run (bool): Execute in dry run mode.  Default is False.
        """
        variables = {
            'entityKey': kwargs.pop('entity_key'),
            'entityType': kwargs.pop('entity_type'),
            'entityClass': kwargs.pop('entity_class')
        }

        timestamp: int = kwargs.pop('timestamp', None)
        properties: Dict = kwargs.pop('properties', None)
        dry_run: bool = kwargs.pop('dry_run', False)

        if timestamp:
            variables.update(timestamp=timestamp)
        if properties:
            variables.update(properties=properties)

        response = self._execute_query(
            query=CREATE_ENTITY,
            variables=variables,
            dry_run=dry_run
        )
        return response['data']['createEntity']

    def delete_entity(self, entity_id: str = None, dry_run: bool = False) -> Dict:
        """ Deletes an entity from the graph.  Note this is a hard delete.

        args:
            entity_id (str): Entity ID for entity to delete
            dry_run (bool): Execute in dry run mode.  Default is False.
        """
        variables = {
            'entityId': entity_id
        }
        response = self._execute_query(DELETE_ENTITY, variables=variables, dry_run=dry_run)
        return response['data']['deleteEntity']

    def create_relationship(self, **kwargs) -> Dict:
        """
        Create a relationship (edge) between two entities (veritces).

        args:
            relationship_key (str): Unique key for the relationship
            relationship_type (str): Value for _type of relationship
            relationship_class (str): Value for _class of relationship
            from_entity_id (str): Entity ID of the source vertex
            to_entity_id (str): Entity ID of the destination vertex
            dry_run (bool): Execute in dry run mode.  Default is False.
        """
        variables = {
            'relationshipKey': kwargs.pop('relationship_key'),
            'relationshipType': kwargs.pop('relationship_type'),
            'relationshipClass': kwargs.pop('relationship_class'),
            'fromEntityId': kwargs.pop('from_entity_id'),
            'toEntityId': kwargs.pop('to_entity_id')
        }

        properties = kwargs.pop('properties', None)
        dry_run = kwargs.pop('dry_run', False)
        if properties:
            variables['properties'] = properties

        response = self._execute_query(
            query=CREATE_RELATIONSHIP,
            variables=variables,
            dry_run=dry_run
        )
        return response['data']['createRelationship']

    def delete_relationship(self, relationship_id: str = None, dry_run: bool = False):
        """ Deletes a relationship between two entities.

        args:
            relationship_id (str): The ID of the relationship
            dry_run (bool): Execute in dry run mode.  Default is False.
        """
        variables = {
            'relationshipId': relationship_id
        }

        response = self._execute_query(
            DELETE_RELATIONSHIP,
            variables=variables,
            dry_run=dry_run
        )
        return response['data']['deleteRelationship']