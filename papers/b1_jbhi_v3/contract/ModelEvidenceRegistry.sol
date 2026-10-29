// SPDX-License-Identifier: MIT
pragma solidity 0.8.34;

/// @notice Anchors model-experiment evidence; display metadata has an append-only event history.
/// @dev Evidence/model-spec/result digests are SHA-256 values computed off-chain. Metadata uses
///      keccak256(abi.encode(dataName, description)). Hashes attest byte identity, not model accuracy.
contract ModelEvidenceRegistry {
    uint256 public constant MAX_NAME_BYTES = 128;
    uint256 public constant MAX_DESCRIPTION_BYTES = 512;
    uint256 public constant MAX_URI_BYTES = 256;

    address public immutable owner;
    mapping(address => bool) public authorizedSubmitters;

    struct Record {
        bytes32 evidenceHash;
        bytes32 modelSpecHash;
        bytes32 resultHash;
        bytes32 metadataHash;
        address submitter;
        uint64 createdAt;
        uint32 metadataVersion;
        string evidenceURI;
        string dataName;
        string description;
        string sourceRecordId;
        string conclusion;
        string modelVersion;
        string confidence;
    }

    struct AnalysisInput {
        bytes32 recordId;
        bytes32 evidenceHash;
        bytes32 modelSpecHash;
        bytes32 resultHash;
        string evidenceURI;
        string dataName;
        string description;
        string sourceRecordId;
        string conclusion;
        string modelVersion;
        string confidence;
    }

    mapping(bytes32 => Record) private records;

    error Unauthorized();
    error InvalidRecordId();
    error InvalidDigest();
    error ZeroSubmitter();
    error EmptyURI();
    error EmptyName();
    error TextTooLong();
    error DuplicateRecord();
    error MissingRecord();
    error InvalidAnalysis();
    error InvalidAnalysisHash();

    event SubmitterAuthorization(address indexed submitter, bool authorized);
    event RecordAnchored(
        bytes32 indexed recordId,
        address indexed submitter,
        bytes32 evidenceHash,
        bytes32 modelSpecHash,
        bytes32 resultHash,
        string evidenceURI
    );
    event MetadataUpdated(
        bytes32 indexed recordId,
        uint32 indexed version,
        bytes32 previousMetadataHash,
        bytes32 metadataHash,
        string dataName,
        string description
    );
    event AnalysisRecorded(
        bytes32 indexed recordId,
        string sourceRecordId,
        string conclusion,
        string modelVersion,
        string confidence
    );

    constructor() {
        owner = msg.sender;
        authorizedSubmitters[msg.sender] = true;
        emit SubmitterAuthorization(msg.sender, true);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier onlySubmitter() {
        if (msg.sender != owner && !authorizedSubmitters[msg.sender]) revert Unauthorized();
        _;
    }

    function setSubmitter(address submitter, bool authorized) external onlyOwner {
        if (submitter == address(0)) revert ZeroSubmitter();
        authorizedSubmitters[submitter] = authorized;
        emit SubmitterAuthorization(submitter, authorized);
    }

    function anchor(
        bytes32 recordId,
        bytes32 evidenceHash,
        bytes32 modelSpecHash,
        bytes32 resultHash,
        string calldata evidenceURI,
        string calldata dataName,
        string calldata description
    ) external onlySubmitter {
        _anchor(recordId, evidenceHash, modelSpecHash, resultHash, evidenceURI, dataName, description);
    }

    /// @notice B1 Ledger.append(ANALYSIS_RECORD), with immutable aggregate conclusion fields.
    function anchorAnalysis(AnalysisInput calldata input) external onlySubmitter {
        if (
            bytes(input.sourceRecordId).length == 0 || bytes(input.sourceRecordId).length > 128
                || bytes(input.conclusion).length == 0 || bytes(input.conclusion).length > 512
                || bytes(input.modelVersion).length == 0 || bytes(input.modelVersion).length > 128
                || bytes(input.confidence).length == 0 || bytes(input.confidence).length > 256
                || sha256(bytes(input.sourceRecordId)) != input.recordId
        ) revert InvalidAnalysis();
        bytes32 expectedResultHash = sha256(
            abi.encode(
                input.sourceRecordId, input.conclusion, input.evidenceHash,
                input.evidenceURI, input.modelVersion, input.confidence
            )
        );
        if (input.resultHash != expectedResultHash) revert InvalidAnalysisHash();
        _anchor(
            input.recordId, input.evidenceHash, input.modelSpecHash, input.resultHash,
            input.evidenceURI, input.dataName, input.description
        );
        Record storage record = records[input.recordId];
        record.sourceRecordId = input.sourceRecordId;
        record.conclusion = input.conclusion;
        record.modelVersion = input.modelVersion;
        record.confidence = input.confidence;
        emit AnalysisRecorded(
            input.recordId, input.sourceRecordId, input.conclusion, input.modelVersion, input.confidence
        );
    }

    function _anchor(
        bytes32 recordId,
        bytes32 evidenceHash,
        bytes32 modelSpecHash,
        bytes32 resultHash,
        string calldata evidenceURI,
        string calldata dataName,
        string calldata description
    ) private {
        if (recordId == bytes32(0)) revert InvalidRecordId();
        if (records[recordId].submitter != address(0)) revert DuplicateRecord();
        if (evidenceHash == bytes32(0) || modelSpecHash == bytes32(0) || resultHash == bytes32(0)) {
            revert InvalidDigest();
        }
        if (bytes(evidenceURI).length == 0) revert EmptyURI();
        if (bytes(evidenceURI).length > MAX_URI_BYTES) revert TextTooLong();
        _validateMetadata(dataName, description);
        bytes32 metadataHash = keccak256(abi.encode(dataName, description));
        Record storage record = records[recordId];
        record.evidenceHash = evidenceHash;
        record.modelSpecHash = modelSpecHash;
        record.resultHash = resultHash;
        record.metadataHash = metadataHash;
        record.submitter = msg.sender;
        record.createdAt = uint64(block.timestamp);
        record.metadataVersion = 1;
        record.evidenceURI = evidenceURI;
        record.dataName = dataName;
        record.description = description;
        emit RecordAnchored(recordId, msg.sender, evidenceHash, modelSpecHash, resultHash, evidenceURI);
        emit MetadataUpdated(recordId, 1, bytes32(0), metadataHash, dataName, description);
    }

    /// @notice Revisions update labels only; evidence/model/result digests and URI remain immutable.
    function updateMetadata(bytes32 recordId, string calldata dataName, string calldata description)
        external
    {
        Record storage record = records[recordId];
        if (record.submitter == address(0)) revert MissingRecord();
        if (
            msg.sender != owner
                && (msg.sender != record.submitter || !authorizedSubmitters[msg.sender])
        ) revert Unauthorized();
        _validateMetadata(dataName, description);
        bytes32 previous = record.metadataHash;
        bytes32 next = keccak256(abi.encode(dataName, description));
        record.metadataHash = next;
        record.metadataVersion += 1;
        record.dataName = dataName;
        record.description = description;
        emit MetadataUpdated(
            recordId, record.metadataVersion, previous, next, dataName, description
        );
    }

    function getRecord(bytes32 recordId) external view returns (Record memory) {
        if (records[recordId].submitter == address(0)) revert MissingRecord();
        return records[recordId];
    }

    function verifyEvidence(bytes32 recordId, bytes32 evidenceHash) external view returns (bool) {
        return records[recordId].submitter != address(0)
            && records[recordId].evidenceHash == evidenceHash;
    }

    function _validateMetadata(string calldata dataName, string calldata description) private pure {
        if (bytes(dataName).length == 0) revert EmptyName();
        if (
            bytes(dataName).length > MAX_NAME_BYTES
                || bytes(description).length > MAX_DESCRIPTION_BYTES
        ) revert TextTooLong();
    }
}
