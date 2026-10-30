// Adaptive material allocation/discovery and failure rollback. No engine link.
#include <array>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#define TB_NO_HELPER_API
#define ORIENT_FATHOM_DYNAMIC_CATALOG 1
#define ORIENT_FATHOM_DYNAMIC_CATALOG_TEST 1
#define ORIENT_FATHOM_FIVE_PIECE_CATALOG 0
#define ORIENT_FATHOM_DIAGNOSTICS 1
#define ORIENT_FATHOM_PREFIX_LENGTH 1
#include "../third_party/fathom/src/tbprobe.c"
#undef min
#undef max
namespace fs=std::filesystem;
void require(bool b,const char*message){if(!b)throw std::runtime_error(message);}
OrientTbDiagnostics snap(){OrientTbDiagnostics d{};orient_tb_diagnostics_snapshot(&d);return d;}
void released(){auto d=snap();for(auto x:d.allocations)require(x.live_bytes==0&&x.allocations==x.frees,"allocation balance");require(d.mapped_bytes==0&&d.map_calls==d.unmap_calls,"mapping balance");require(d.piece_count==0&&d.pawn_count==0&&d.piece_capacity==0&&d.pawn_capacity==0&&TB_LARGEST==0,"teardown catalogue state");require(TB_MaxCardinality==0&&TB_MaxCardinalityDTM==0,"teardown retains internal cardinality");for(const auto&entry:tbHash)require(entry.key==0&&entry.ptr==nullptr,"teardown retains catalogue hash pointers");}
struct Temp{fs::path path=fs::temp_directory_path()/("Orient adaptive "+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));Temp(){fs::create_directory(path);}~Temp(){std::error_code ec;fs::remove_all(path,ec);}};
void link(const fs::path&a,const fs::path&b){std::error_code e;fs::create_symlink(fs::absolute(a),b,e);if(e)fs::copy_file(a,b);}
unsigned queen(){return tb_probe_wdl(9,UINT64_C(1)<<62,1|(UINT64_C(1)<<62),8,0,0,0,0,0,0,0,true);}
unsigned root(){std::array<unsigned,TB_MAX_MOVES> moves{};return tb_probe_root(9,UINT64_C(1)<<62,1|(UINT64_C(1)<<62),8,0,0,0,0,0,0,0,true,moves.data());}
int main(int argc,char**argv){try{
 static_assert(TB_PIECES==7&&TB_HASHBITS==12);static_assert(sizeof(((EncInfo*)nullptr)->pieces)==7);
 const bool regressionsOnly=argc>1&&std::string(argv[1])=="--regressions-only";
 if(regressionsOnly&&argc!=3)throw std::runtime_error("usage: test_dynamic_catalog --regressions-only TABLE_DIRECTORY");
 if(!regressionsOnly&&argc>2)throw std::runtime_error("usage: test_dynamic_catalog [TABLE_DIRECTORY]");
 const char*env=std::getenv("ORIENT_SYZYGY_PATH");if(argc<2&&!env){std::cout<<"Set ORIENT_SYZYGY_PATH for adaptive-catalogue tests\n";return 77;}fs::path data=regressionsOnly?argv[2]:(argc>1?argv[1]:env);tb_free();released();
 Temp empty;std::ofstream(empty.path/"a")<<"unrelated";std::ofstream(empty.path/"abcd")<<"unrelated";
 auto before=snap();require(tb_init(empty.path.string().c_str()),"empty init");auto after=snap();
 require(after.open_attempts==before.open_attempts&&after.piece_capacity==0&&after.pawn_capacity==0,"empty directory discovery bound");require(queen()==TB_RESULT_FAILED,"empty outcome");tb_free();released();
 require(tb_init((empty.path/"missing").string().c_str()),"missing path fallback");require(TB_LARGEST==0&&queen()==TB_RESULT_FAILED,"missing path outcome");tb_free();released();
 require(tb_init("")&&tb_init("<empty>"),"empty path sentinel");tb_free();released();
 // Fold names conservatively even on case-sensitive POSIX. We test the
 // scanner directly: opening lowercase aliases depends on filesystem policy.
 Temp folded;std::ofstream(folded.path/"kqqvk.rtbw")<<"placeholder";
 require(tb_init(folded.path.string().c_str())&&orient_tb_discovery_bound()==4,"lowercase discovery bound");tb_free();released();
 fs::remove(folded.path/"kqqvk.rtbw");std::ofstream(folded.path/"KQQQVK.RTBW")<<"placeholder";
 require(tb_init(folded.path.string().c_str())&&orient_tb_discovery_bound()==5,"uppercase discovery bound");tb_free();released();
 orientTbForceListingFailure=true;before=snap();
 require(tb_init(empty.path.string().c_str())&&orient_tb_discovery_bound()==TB_PIECES,"listing failure fallback bound");
 require(snap().open_attempts>before.open_attempts,"listing failure must use original discovery");
 tb_free();released();orientTbForceListingFailure=false;
 Temp partial;link(data/"KQvK.rtbw",partial.path/"KQvK.rtbw");
 before=snap();require(tb_init(partial.path.string().c_str()),"partial init");after=snap();
 require(TB_LARGEST==3&&after.piece_capacity==1&&after.pawn_capacity==0,"adaptive partial capacities");
 require(after.open_attempts-before.open_attempts==7,"partial discovery must use observed bound");require(queen()==TB_WIN&&root()==TB_RESULT_FAILED,"partial missing DTZ");tb_free();released();
 require(queen()==TB_RESULT_FAILED&&root()==TB_RESULT_FAILED,"post-teardown probes must be unavailable");
 for(const char*sentinel:{"","<empty>"}){
  require(tb_init(partial.path.string().c_str())&&queen()==TB_WIN,"sentinel fixture init");
  require(tb_init(sentinel)&&TB_LARGEST==0&&TB_MaxCardinality==0&&TB_MaxCardinalityDTM==0,"sentinel retains cardinality");
  for(const auto&entry:tbHash)require(entry.key==0&&entry.ptr==nullptr,"sentinel retains catalogue hash pointers");
  require(queen()==TB_RESULT_FAILED&&root()==TB_RESULT_FAILED,"sentinel probes must be unavailable");tb_free();released();
 }
 link(data/"KQvK.rtbz",partial.path/"KQvK.rtbz");link(data/"KQvK.rtbw",partial.path/"KQvK.rtbm");
 require(tb_init(partial.path.string().c_str())&&numDtm==1&&root()!=TB_RESULT_FAILED,"DTM/DTZ retained");
 auto allocations=snap().allocations[ORIENT_TB_CATALOG].allocations;
 require(tb_init(partial.path.string().c_str())&&queen()==TB_WIN,"same-path reinit");require(snap().allocations[ORIENT_TB_CATALOG].allocations==allocations,"equal-size catalogue reuse");tb_free();released();
 const auto repeated=partial.path.string()+std::string(1,SEP_CHAR)+partial.path.string();require(tb_init(repeated.c_str())&&queen()==TB_WIN,"repeated path list");tb_free();released();
 for(const auto&pathList:{partial.path.string()+SEP_CHAR,
                         partial.path.string()+std::string(2,SEP_CHAR),
                         SEP_CHAR+partial.path.string()+SEP_CHAR}){
  require(tb_init(pathList.c_str())&&numPaths==1&&queen()==TB_WIN,"empty path-list component must be skipped");tb_free();released();
 }
 for(unsigned separators:{1U,2U}){
  require(tb_init(std::string(separators,SEP_CHAR).c_str())&&numPaths==0&&TB_LARGEST==0,"separator-only path list must be empty");
  require(queen()==TB_RESULT_FAILED&&root()==TB_RESULT_FAILED,"empty path list manufactured an outcome");tb_free();released();
 }
 fs::remove(partial.path/"KQvK.rtbm");
 // Aligned placeholders exercise discovery only, never six/seven-piece probes.
 link(data/"KQvK.rtbw",partial.path/"KQQQvKQ.rtbw");require(tb_init(partial.path.string().c_str())&&TB_LARGEST==6&&snap().piece_capacity==2,"six-piece discovery retained");tb_free();released();
 link(data/"KQvK.rtbw",partial.path/"KQQQQvKQ.rtbw");require(tb_init(partial.path.string().c_str())&&TB_LARGEST==7&&snap().piece_capacity==3,"seven-piece discovery retained");tb_free();released();
 if(regressionsOnly){std::cout<<"Adaptive catalogue regression fixtures: teardown, empty sentinels, path-list boundaries, discovery and reuse passed\n";return 0;}
 before=snap();require(tb_init(data.string().c_str()),"complete init");after=snap();
 require(TB_LARGEST==5&&after.piece_count==84&&after.pawn_count==61&&after.piece_capacity==84&&after.pawn_capacity==61,"complete counts/capacities");
 require(after.open_attempts-before.open_attempts==435,"complete discovery open count");
 require(after.allocations[ORIENT_TB_CATALOG].live_bytes==84*sizeof(PieceEntry)+61*sizeof(PawnEntry),"exact catalogue requested payload");require(queen()==TB_WIN&&root()!=TB_RESULT_FAILED,"complete query");
 require(tb_init(partial.path.string().c_str())&&snap().piece_capacity==3&&queen()==TB_WIN,"catalogue resizing and stale-map removal");tb_free();released();
 for(bool allocation:{false,true}){
  if(allocation)orientTbForceAllocationFailure=true;else orientTbStageLimit=0;
  require(!tb_init(data.string().c_str()),"forced failure accepted partial catalogue");
  require(TB_LARGEST==0&&TB_MaxCardinality==0&&TB_MaxCardinalityDTM==0&&queen()==TB_RESULT_FAILED,"failure retained outcome");
  for(const auto&entry:tbHash)require(entry.key==0&&entry.ptr==nullptr,"failure retained hash pointers");released();
  orientTbStageLimit=TB_MAX_PIECE+TB_MAX_PAWN;orientTbForceAllocationFailure=false;
  require(tb_init(data.string().c_str())&&queen()==TB_WIN,"recovery after failure");tb_free();released();
 }
 for(unsigned failAt:{1U,2U}){
  const auto prior=snap().allocations[ORIENT_TB_CATALOG];orientTbAllocationFailureAt=failAt;
  require(!tb_init(data.string().c_str()),"per-allocation failure accepted catalogue");
  require(orientTbAllocationAttempts==2,"both catalogue allocation sites must execute");
  const auto current=snap().allocations[ORIENT_TB_CATALOG];
  require(current.allocations==prior.allocations+1&&current.frees==prior.frees+1,"partial allocation must be recorded and freed");
  require(TB_LARGEST==0&&TB_MaxCardinality==0&&queen()==TB_RESULT_FAILED,"partial failure retained usable tables");
  for(const auto&entry:tbHash)require(entry.key==0&&entry.ptr==nullptr,"partial failure retained hashes");released();
  orientTbAllocationFailureAt=0;require(tb_init(data.string().c_str())&&queen()==TB_WIN,"partial allocation recovery");tb_free();released();
 }
 std::cout<<"Adaptive catalogue: complete/partial/empty/missing paths, 3-7 discovery, payload, reuse, resize, rollback and teardown passed\n";
}catch(const std::exception&e){tb_free();std::cerr<<e.what()<<'\n';return 1;}}
