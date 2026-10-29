// SPDX-License-Identifier: MIT
pragma solidity 0.8.34;

import {ModelEvidenceRegistry} from "../src/ModelEvidenceRegistry.sol";

interface Vm {
    function prank(address) external;
    function expectRevert(bytes4) external;
    function recordLogs() external;
    struct Log { bytes32[] topics; bytes data; address emitter; }
    function getRecordedLogs() external returns (Log[] memory);
}

contract ModelEvidenceRegistryTest {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    ModelEvidenceRegistry private registry;
    bytes32 private constant ID = keccak256("model-record-1");
    bytes32 private constant EVIDENCE = 0xee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e;
    bytes32 private constant MODEL = 0xd56ef9411f5534ea74845f09ce4633f2a96f1b2ecf3cdc49f33c2b408597c011;
    bytes32 private constant RESULT = 0xb084cbb14ffabd3abf0a8e32ce94947c2fffb025063a7f84fd0a152d3dacc795;
    address private constant WRITER = address(0x1234);
    address private constant OTHER = address(0x5678);

    function setUp() public { registry = new ModelEvidenceRegistry(); }

    function _anchor() private {
        registry.anchor(ID, EVIDENCE, MODEL, RESULT, "urn:sha256:evidence", "MODEL_RECORD_001", "Temporary description");
    }

    function testAnchorRoundTrip() public {
        _anchor();
        ModelEvidenceRegistry.Record memory r = registry.getRecord(ID);
        require(r.evidenceHash == EVIDENCE && r.modelSpecHash == MODEL && r.resultHash == RESULT);
        require(r.submitter == address(this) && r.metadataVersion == 1);
        require(r.metadataHash == keccak256(abi.encode("MODEL_RECORD_001", "Temporary description")));
        require(registry.verifyEvidence(ID, EVIDENCE));
    }

    function testUnauthorizedAnchor() public {
        vm.prank(OTHER); vm.expectRevert(ModelEvidenceRegistry.Unauthorized.selector); _anchor();
    }

    function testOwnerCanGrantAndRevoke() public {
        registry.setSubmitter(WRITER, true);
        vm.prank(WRITER); _anchor();
        registry.setSubmitter(WRITER, false);
        vm.prank(WRITER); vm.expectRevert(ModelEvidenceRegistry.Unauthorized.selector);
        registry.anchor(keccak256("second"), EVIDENCE, MODEL, RESULT, "urn:e", "n", "d");
    }

    function testAuthorizationRestrictedToOwner() public {
        vm.prank(OTHER); vm.expectRevert(ModelEvidenceRegistry.Unauthorized.selector);
        registry.setSubmitter(WRITER, true);
    }

    function testRejectZeroSubmitter() public {
        vm.expectRevert(ModelEvidenceRegistry.ZeroSubmitter.selector);
        registry.setSubmitter(address(0), true);
    }

    function testDuplicateRecordRejected() public {
        _anchor(); vm.expectRevert(ModelEvidenceRegistry.DuplicateRecord.selector); _anchor();
    }

    function testRejectZeroRecordId() public {
        vm.expectRevert(ModelEvidenceRegistry.InvalidRecordId.selector);
        registry.anchor(bytes32(0), EVIDENCE, MODEL, RESULT, "urn:e", "n", "d");
    }

    function testRejectZeroEvidenceHash() public {
        vm.expectRevert(ModelEvidenceRegistry.InvalidDigest.selector);
        registry.anchor(ID, bytes32(0), MODEL, RESULT, "urn:e", "n", "d");
    }

    function testRejectZeroModelHash() public {
        vm.expectRevert(ModelEvidenceRegistry.InvalidDigest.selector);
        registry.anchor(ID, EVIDENCE, bytes32(0), RESULT, "urn:e", "n", "d");
    }

    function testRejectZeroResultHash() public {
        vm.expectRevert(ModelEvidenceRegistry.InvalidDigest.selector);
        registry.anchor(ID, EVIDENCE, MODEL, bytes32(0), "urn:e", "n", "d");
    }

    function testRejectEmptyURI() public {
        vm.expectRevert(ModelEvidenceRegistry.EmptyURI.selector);
        registry.anchor(ID, EVIDENCE, MODEL, RESULT, "", "n", "d");
    }

    function testRejectEmptyName() public {
        vm.expectRevert(ModelEvidenceRegistry.EmptyName.selector);
        registry.anchor(ID, EVIDENCE, MODEL, RESULT, "urn:e", "", "d");
    }

    function testRejectOversizedName() public {
        vm.expectRevert(ModelEvidenceRegistry.TextTooLong.selector);
        registry.anchor(ID, EVIDENCE, MODEL, RESULT, "urn:e", string(new bytes(129)), "d");
    }

    function testRejectOversizedDescription() public {
        vm.expectRevert(ModelEvidenceRegistry.TextTooLong.selector);
        registry.anchor(ID, EVIDENCE, MODEL, RESULT, "urn:e", "n", string(new bytes(513)));
    }

    function testRejectOversizedURI() public {
        vm.expectRevert(ModelEvidenceRegistry.TextTooLong.selector);
        registry.anchor(ID, EVIDENCE, MODEL, RESULT, string(new bytes(257)), "n", "d");
    }

    function testMetadataRevisionPreservesEvidence() public {
        _anchor(); ModelEvidenceRegistry.Record memory beforeRecord = registry.getRecord(ID);
        registry.updateMetadata(ID, "FINAL_DATA_NAME", "Final description supplied by author");
        ModelEvidenceRegistry.Record memory afterRecord = registry.getRecord(ID);
        require(afterRecord.evidenceHash == beforeRecord.evidenceHash);
        require(afterRecord.modelSpecHash == beforeRecord.modelSpecHash);
        require(afterRecord.resultHash == beforeRecord.resultHash);
        require(keccak256(bytes(afterRecord.evidenceURI)) == keccak256(bytes(beforeRecord.evidenceURI)));
        require(afterRecord.createdAt == beforeRecord.createdAt && afterRecord.metadataVersion == 2);
        require(afterRecord.metadataHash != beforeRecord.metadataHash);
    }

    function testOtherAuthorizedWriterCannotRenameRecord() public {
        _anchor(); registry.setSubmitter(OTHER, true);
        vm.prank(OTHER); vm.expectRevert(ModelEvidenceRegistry.Unauthorized.selector);
        registry.updateMetadata(ID, "changed", "changed");
    }

    function testRevokedWriterCannotRenameRecord() public {
        registry.setSubmitter(WRITER, true); vm.prank(WRITER); _anchor();
        registry.setSubmitter(WRITER, false);
        vm.prank(WRITER); vm.expectRevert(ModelEvidenceRegistry.Unauthorized.selector);
        registry.updateMetadata(ID, "changed", "changed");
    }

    function testMissingReadRejected() public {
        vm.expectRevert(ModelEvidenceRegistry.MissingRecord.selector); registry.getRecord(ID);
    }

    function testMissingUpdateRejected() public {
        vm.expectRevert(ModelEvidenceRegistry.MissingRecord.selector);
        registry.updateMetadata(ID, "n", "d");
    }

    function testMissingOrTamperedEvidenceDoesNotVerify() public {
        require(!registry.verifyEvidence(ID, EVIDENCE)); _anchor();
        require(!registry.verifyEvidence(ID, sha256("tampered")));
    }

    function testRevisionEventRetainsPreviousDigest() public {
        _anchor(); bytes32 previous = registry.getRecord(ID).metadataHash;
        vm.recordLogs(); registry.updateMetadata(ID, "new name", "new description");
        Vm.Log[] memory logs = vm.getRecordedLogs(); require(logs.length == 1);
        require(logs[0].topics[1] == ID && uint256(logs[0].topics[2]) == 2);
        (bytes32 oldHash, bytes32 nextHash, string memory name, string memory description) =
            abi.decode(logs[0].data, (bytes32, bytes32, string, string));
        require(oldHash == previous);
        require(nextHash == keccak256(abi.encode(name, description)));
    }

    function testFuzzMetadataCannotChangeEvidence(bytes32 digest, uint16 nameLength) public {
        if (digest == bytes32(0)) digest = bytes32(uint256(1));
        registry.anchor(ID, digest, MODEL, RESULT, "urn:e", "n", "d");
        registry.updateMetadata(ID, string(new bytes(1 + (uint256(nameLength) % 128))), "replacement");
        require(registry.getRecord(ID).evidenceHash == digest);
        require(registry.verifyEvidence(ID, digest));
    }

    function testFuzzDifferentDigestCannotVerify(bytes32 changed) public {
        _anchor(); if (changed == EVIDENCE) changed = bytes32(uint256(EVIDENCE) ^ 1);
        require(!registry.verifyEvidence(ID, changed));
    }

    function _analysisInput() private pure returns (ModelEvidenceRegistry.AnalysisInput memory a) {
        a.sourceRecordId = "B1/B_stage_group/policy";
        a.recordId = sha256(bytes(a.sourceRecordId));
        a.evidenceHash = EVIDENCE;
        a.modelSpecHash = MODEL;
        a.evidenceURI = "repo://experiments/b1_cost_acquisition/results/results.json";
        a.dataName = "MODEL_RECORD_001";
        a.description = "Author display metadata pending";
        a.conclusion = "Frozen B1 aggregate model result";
        a.modelVersion = "protocol:ad1acf74a882";
        a.confidence = "paired bootstrap";
        a.resultHash = sha256(abi.encode(a.sourceRecordId, a.conclusion, a.evidenceHash,
            a.evidenceURI, a.modelVersion, a.confidence));
    }

    function testAnalysisRecordRoundTrip() public {
        ModelEvidenceRegistry.AnalysisInput memory a = _analysisInput();
        registry.anchorAnalysis(a);
        ModelEvidenceRegistry.Record memory r = registry.getRecord(a.recordId);
        require(keccak256(bytes(r.conclusion)) == keccak256(bytes(a.conclusion)));
        require(r.resultHash == a.resultHash && r.evidenceHash == EVIDENCE);
        registry.updateMetadata(a.recordId, "Author final title", "Author final description");
        r = registry.getRecord(a.recordId);
        require(keccak256(bytes(r.conclusion)) == keccak256(bytes(a.conclusion)));
        require(r.resultHash == a.resultHash && r.modelSpecHash == MODEL);
    }

    function testAnalysisRejectsMismatchedResultHash() public {
        ModelEvidenceRegistry.AnalysisInput memory a = _analysisInput();
        a.conclusion = "changed after digest computation";
        vm.expectRevert(ModelEvidenceRegistry.InvalidAnalysisHash.selector);
        registry.anchorAnalysis(a);
    }

    function testAnalysisRejectsMismatchedRecordId() public {
        ModelEvidenceRegistry.AnalysisInput memory a = _analysisInput(); a.recordId = ID;
        vm.expectRevert(ModelEvidenceRegistry.InvalidAnalysis.selector); registry.anchorAnalysis(a);
    }

    function testAnalysisRejectsOversizedConclusion() public {
        ModelEvidenceRegistry.AnalysisInput memory a = _analysisInput();
        a.conclusion = string(new bytes(513));
        vm.expectRevert(ModelEvidenceRegistry.InvalidAnalysis.selector); registry.anchorAnalysis(a);
    }

    function testAnalysisUnauthorizedWriterRejected() public {
        ModelEvidenceRegistry.AnalysisInput memory a = _analysisInput();
        vm.prank(OTHER); vm.expectRevert(ModelEvidenceRegistry.Unauthorized.selector);
        registry.anchorAnalysis(a);
    }

    function testRenameAtMaximumAcceptedLengths() public {
        _anchor(); bytes memory name = new bytes(128); bytes memory description = new bytes(512);
        for(uint256 i=0;i<128;i++) name[i]=0x4e;
        for(uint256 i=0;i<512;i++) description[i]=0x44;
        registry.updateMetadata(ID,string(name),string(description));
        ModelEvidenceRegistry.Record memory r = registry.getRecord(ID);
        require(bytes(r.dataName).length==128 && bytes(r.description).length==512);
        require(r.evidenceHash==EVIDENCE);
    }
}
