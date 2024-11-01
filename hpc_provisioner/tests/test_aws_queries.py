import logging
from unittest.mock import MagicMock, call, patch

import pytest
from hpc_provisioner.aws_queries import (
    CouldNotDetermineEFSException,
    CouldNotDetermineKeyPairException,
    CouldNotDetermineSecurityGroupException,
    OutOfSubnetsException,
    claim_subnet,
    get_available_subnet,
    get_efs,
    get_keypair,
    get_security_group,
)
from hpc_provisioner.dynamodb_actions import SubnetAlreadyRegisteredException

logger = logging.getLogger("test_logger")
fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(msg)s")
fh = logging.FileHandler("./test.log")
fh.setFormatter(fmt)
fh.setLevel(logging.DEBUG)
sh = logging.StreamHandler()
sh.setFormatter(fmt)
sh.setLevel(logging.DEBUG)
logger.addHandler(fh)
logger.addHandler(sh)
logger.setLevel(logging.DEBUG)


@pytest.mark.parametrize(
    "keypairs",
    [
        {"KeyPairs": [{"KeyName": "keypair-1"}]},
    ],
)
def test_get_keypair(keypairs):
    mock_ec2_client = MagicMock()
    mock_ec2_client.describe_key_pairs.return_value = keypairs
    keypair = get_keypair(mock_ec2_client)
    assert keypair == keypairs["KeyPairs"][0]["KeyName"]


@pytest.mark.parametrize(
    "keypairs",
    [
        {"KeyPairs": []},
        {"KeyPairs": ["keypair-1", "keypair-2"]},
    ],
)
def test_get_keypair_fails(keypairs):
    mock_ec2_client = MagicMock()
    mock_ec2_client.describe_key_pairs.return_value = keypairs
    with pytest.raises(
        CouldNotDetermineKeyPairException,
        match=str(keypairs["KeyPairs"]).replace("[", "\\["),
    ):
        get_keypair(mock_ec2_client)


@pytest.mark.parametrize(
    "filesystems",
    [
        {
            "FileSystems": [
                {
                    "FileSystemId": "fs-123",
                    "Tags": [
                        {"Key": "HPC_Goal", "Value": "compute_cluster"},
                        {"Key": "SBO_Billing", "Value": "hpc"},
                    ],
                },
                {
                    "FileSystemId": "fs-234",
                    "Tags": [{}],
                },
            ]
        },
        {
            "FileSystems": [
                {
                    "FileSystemId": "fs-123",
                    "Tags": [
                        {"Key": "HPC_Goal", "Value": "compute_cluster"},
                        {"key": "SBO_Billing", "Value": "hpc"},
                    ],
                },
                {
                    "FileSystemId": "fs-234",
                    "Tags": [{}],
                },
            ]
        },
    ],
)
def test_get_efs(filesystems):
    mock_efs_client = MagicMock()
    mock_efs_client.describe_file_systems.return_value = filesystems
    efs = get_efs(mock_efs_client)
    assert efs == filesystems["FileSystems"][0]["FileSystemId"]


@pytest.mark.parametrize(
    "filesystems",
    [
        {"FileSystems": []},
        {
            "FileSystems": [
                {
                    "FileSystemId": "fs-123",
                    "Tags": [{"Key": "HPC_Goal", "Value": "compute_cluster"}],
                },
                {
                    "FileSystemId": "fs-234",
                    "Tags": [{"Key": "HPC_Goal", "Value": "compute_cluster"}],
                },
            ]
        },
    ],
)
def test_get_efs_fails(filesystems):
    mock_efs_client = MagicMock()
    mock_efs_client.describe_file_systems.return_value = filesystems
    with pytest.raises(
        CouldNotDetermineEFSException,
        match=str([fs["FileSystemId"] for fs in filesystems["FileSystems"]]).replace("[", "\\["),
    ):
        get_efs(mock_efs_client)


@pytest.mark.parametrize(
    "security_groups",
    [
        {
            "SecurityGroups": [
                {"GroupId": "sg-1", "Tags": [{"Key": "HPC_Goal", "Value": "compute_cluster"}]},
            ]
        },
    ],
)
def test_get_security_group(security_groups):
    mock_ec2_client = MagicMock()
    mock_ec2_client.describe_security_groups.return_value = security_groups
    security_group = get_security_group(mock_ec2_client)
    assert security_group == security_groups["SecurityGroups"][0]["GroupId"]


@pytest.mark.parametrize(
    "security_groups",
    [
        {"SecurityGroups": []},
        {
            "SecurityGroups": [
                {"GroupId": "sg-1", "Tags": [{"Key": "HPC_Goal", "Value": "compute_cluster"}]},
                {"GroupId": "sg-2", "Tags": [{"Key": "HPC_Goal", "Value": "compute_cluster"}]},
            ]
        },
    ],
)
def test_get_security_group_fails(security_groups):
    mock_ec2_client = MagicMock()
    mock_ec2_client.describe_security_groups.return_value = security_groups
    with pytest.raises(
        CouldNotDetermineSecurityGroupException,
        match=str([sg["GroupId"] for sg in security_groups["SecurityGroups"]]).replace("[", "\\["),
    ):
        get_security_group(mock_ec2_client)


@patch("hpc_provisioner.aws_queries.free_subnet")
@pytest.mark.parametrize(
    "ec2_subnets,claimed_subnets,cluster_name",
    [
        ([{"SubnetId": "sub-1"}, {"SubnetId": "sub-2"}], {"sub-1": "cluster1"}, "cluster1"),
        (
            [{"SubnetId": "sub-1"}, {"SubnetId": "sub-2"}, {"SubnetId": "sub-3"}],
            {"sub-1": "cluster1", "sub-2": "cluster1"},
            "cluster1",
        ),
    ],
)
def test_claim_subnet_existing_claims(
    patched_free_subnet, ec2_subnets, claimed_subnets, cluster_name
):
    """
    1. One subnet was already claimed: nothing gets released, one gets returned
    2. Two subnets were already claimed: one gets released, one gets returned
    """
    mock_dynamodb_client = MagicMock()
    with patch("hpc_provisioner.aws_queries.get_registered_subnets") as mock_get_registered_subnets:
        mock_get_registered_subnets.return_value = claimed_subnets
        subnet = claim_subnet(mock_dynamodb_client, ec2_subnets, cluster_name)
        if len(claimed_subnets.keys()) == 1:
            patched_free_subnet.assert_not_called()
        else:
            assert patched_free_subnet.call_count == 1
        assert subnet == [*claimed_subnets][-1]


@patch("hpc_provisioner.aws_queries.free_subnet")
def test_all_ec2_subnets_are_registered(patched_free_subnet):
    ec2_subnets = [{"SubnetId": "sub-1"}, {"SubnetId": "sub-2"}]
    mock_dynamodb_client = MagicMock()
    with patch("hpc_provisioner.aws_queries.get_registered_subnets") as mock_get_registered_subnets:
        mock_get_registered_subnets.return_value = {"sub-1": "cluster1", "sub-2": "cluster2"}
        with pytest.raises(OutOfSubnetsException, match="All subnets are in use"):
            claim_subnet(mock_dynamodb_client, ec2_subnets, "cluster3")
        patched_free_subnet.assert_not_called()


@patch("hpc_provisioner.aws_queries.get_subnet", return_value={"sub-2": "cluster1"})
@patch("hpc_provisioner.aws_queries.free_subnet")
@patch("hpc_provisioner.aws_queries.logger")
def test_claim_subnet_claimed_between_list_and_register(
    patched_logger,
    patched_free_subnet,
    patched_get_subnet,
):
    """
    The subnet was not part of get_registered_subnets,
    but was claimed while we were checking the result of that call
    for existing claims for our cluster.
    """
    mock_dynamodb_client = MagicMock()
    ec2_subnets = [{"SubnetId": "sub-1"}, {"SubnetId": "sub-2"}]
    cluster_name = "cluster1"
    with patch("hpc_provisioner.aws_queries.get_registered_subnets") as mock_get_registered_subnets:
        mock_get_registered_subnets.return_value = {}
        with patch("hpc_provisioner.aws_queries.register_subnet") as mock_register_subnet:
            mock_register_subnet.side_effect = [SubnetAlreadyRegisteredException(), None]
            subnet = claim_subnet(mock_dynamodb_client, ec2_subnets, cluster_name)
    patched_free_subnet.assert_not_called()
    patched_logger.debug.assert_any_call("Subnet was registered just before us - continuing")
    patched_get_subnet.assert_called_once_with(mock_dynamodb_client, "sub-2")
    assert subnet == "sub-2"


@patch(
    "hpc_provisioner.aws_queries.get_subnet",
    side_effect=[{"sub-1": "cluster1"}, {"sub-2": "cluster2"}],
)
@patch("hpc_provisioner.aws_queries.free_subnet")
@patch("hpc_provisioner.aws_queries.logger")
def test_claim_subnet_claimed_between_register_and_write(
    patched_logger,
    patched_free_subnet,
    patched_get_subnet,
):
    """
    The subnet was not part of get_registered_subnets,
    but was registered at the same time as someone else (simultaneous writes).
    The other write won.
    """
    mock_dynamodb_client = MagicMock()
    ec2_subnets = [{"SubnetId": "sub-1"}, {"SubnetId": "sub-2"}]
    cluster_name = "cluster2"

    with patch("hpc_provisioner.aws_queries.get_registered_subnets") as mock_get_registered_subnets:
        mock_get_registered_subnets.return_value = {}
        with patch("hpc_provisioner.aws_queries.register_subnet") as mock_register_subnet:
            mock_register_subnet.return_value = None
            subnet = claim_subnet(mock_dynamodb_client, ec2_subnets, cluster_name)
    patched_free_subnet.assert_not_called()
    patched_logger.info.assert_any_call("Subnet sub-1 already claimed for cluster cluster1")
    first_get_subnet = call(mock_dynamodb_client, "sub-1")
    second_get_subnet = call(mock_dynamodb_client, "sub-2")
    patched_get_subnet.assert_has_calls([first_get_subnet, second_get_subnet])
    assert subnet == "sub-2"


@patch(
    "hpc_provisioner.aws_queries.get_subnet",
    return_value={"sub-1": "cluster1"},
)
@patch("hpc_provisioner.aws_queries.free_subnet")
@patch("hpc_provisioner.aws_queries.logger")
def test_claim_subnet_happy_path(
    patched_logger,
    patched_free_subnet,
    patched_get_subnet,
):
    """
    No weird behaviour, just claiming a subnet that nobody else is trying to claim.
    """

    mock_dynamodb_client = MagicMock()
    ec2_subnets = [{"SubnetId": "sub-1"}, {"SubnetId": "sub-2"}]
    cluster_name = "cluster1"

    with patch("hpc_provisioner.aws_queries.get_registered_subnets") as mock_get_registered_subnets:
        mock_get_registered_subnets.return_value = {}
        with patch("hpc_provisioner.aws_queries.register_subnet") as mock_register_subnet:
            mock_register_subnet.return_value = None
            subnet = claim_subnet(mock_dynamodb_client, ec2_subnets, cluster_name)
    patched_free_subnet.assert_not_called()
    patched_get_subnet.assert_called_once_with(mock_dynamodb_client, "sub-1")
    assert subnet == "sub-1"


def test_no_available_subnets():
    mock_ec2_client = MagicMock()
    mock_ec2_client.describe_subnets.return_value = {"Subnets": []}
    with pytest.raises(OutOfSubnetsException):
        get_available_subnet(mock_ec2_client, "cluster1")


@patch("hpc_provisioner.aws_queries.dynamodb_client")
@patch("hpc_provisioner.aws_queries.claim_subnet", side_effect=OutOfSubnetsException())
@patch("hpc_provisioner.aws_queries.logger")
@patch("hpc_provisioner.aws_queries.time")
def test_out_of_subnets(mock_time, mock_logger, mock_claim_subnet, mock_dynamodb_client):
    mock_ec2_client = MagicMock()
    mock_ec2_client.describe_subnets.return_value = {
        "Subnets": [{"SubnetId": "sub-1"}, {"SubnetId": "sub-2"}]
    }
    with pytest.raises(OutOfSubnetsException):
        get_available_subnet(mock_ec2_client, "cluster1")
    mock_logger.critical.assert_any_call(
        "All subnets are in use - either deploy more or remove some pclusters"
    )
    mock_time.sleep.assert_called_once_with(10)


@patch("hpc_provisioner.aws_queries.claim_subnet", return_value="sub-1")
@patch("hpc_provisioner.aws_queries.dynamodb_client")
def test_get_available_subnet(mock_dynamodb_client, mock_claim_subnet):
    ec2_subnets = {"Subnets": [{"SubnetId": "sub-1"}, {"SubnetId": "sub-2"}]}
    cluster_name = "cluster1"
    mock_ec2_client = MagicMock()
    mock_ec2_client.describe_subnets.return_value = ec2_subnets
    subnet = get_available_subnet(mock_ec2_client, cluster_name)
    mock_claim_subnet.assert_called_once_with(
        mock_dynamodb_client(), ec2_subnets["Subnets"], cluster_name
    )
    assert subnet == "sub-1"
