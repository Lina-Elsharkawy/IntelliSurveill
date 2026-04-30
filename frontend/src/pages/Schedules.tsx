// import { useState, useEffect } from "react";
// import { Grid3x3, List, Search, Edit, Trash } from "lucide-react";
// import { DashboardLayout } from "@/components/DashboardLayout";
// import { Button } from "@/components/ui/button";
// import { Input } from "@/components/ui/input";
// import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
// import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
// import { Badge } from "@/components/ui/badge";
// import { Label } from "@/components/ui/label";

// import {
//   getAllSchedules,
//   createSchedule,
//   updateSchedule,
//   deleteSchedule,
// } from "@/services/schedules";

// type ScheduleType = {
//   id: number;
//   name: string;
//   access_start_time: string;
//   access_end_time: string;
//   applies_to_weekdays: boolean;
//   applies_to_weekends: boolean;
//   specific_dates: string[] | null;
// };

// export default function Schedules() {
//   const [schedules, setSchedules] = useState<ScheduleType[]>([]);
//   const [loading, setLoading] = useState(true);
//   const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
//   const [search, setSearch] = useState("");

//   const [editingSchedule, setEditingSchedule] = useState<ScheduleType | null>(null);

//   // Form state
//   const [name, setName] = useState("");
//   const [startTime, setStartTime] = useState("09:00");
//   const [endTime, setEndTime] = useState("17:00");
//   const [weekdays, setWeekdays] = useState(true);
//   const [weekends, setWeekends] = useState(false);
//   const [specificDates, setSpecificDates] = useState<string>("");

//   // Fetch schedules
//   useEffect(() => {
//     const fetchSchedules = async () => {
//       try {
//         const data = await getAllSchedules();
//         setSchedules(data);
//       } catch (err) {
//         console.error(err);
//       } finally {
//         setLoading(false);
//       }
//     };
//     fetchSchedules();
//   }, []);

//   const resetForm = () => {
//     setName("");
//     setStartTime("09:00");
//     setEndTime("17:00");
//     setWeekdays(true);
//     setWeekends(false);
//     setSpecificDates("");
//   };

//   const handleAdd = async () => {
//     try {
//       const newSchedule = await createSchedule({
//         name,
//         access_start_time: startTime,
//         access_end_time: endTime,
//         applies_to_weekdays: weekdays,
//         applies_to_weekends: weekends,
//         specific_dates: specificDates ? specificDates.split(",") : null,
//       });
//       setSchedules((prev) => [...prev, newSchedule]);
//       resetForm();
//     } catch (err) {
//       console.error(err);
//     }
//   };

//   const handleEditClick = (s: ScheduleType) => {
//     setEditingSchedule(s);
//     setName(s.name);
//     setStartTime(s.access_start_time);
//     setEndTime(s.access_end_time);
//     setWeekdays(s.applies_to_weekdays);
//     setWeekends(s.applies_to_weekends);
//     setSpecificDates(s.specific_dates ? s.specific_dates.join(",") : "");
//   };

//   const handleUpdateSubmit = async () => {
//     if (!editingSchedule) return;
//     try {
//       const updated = await updateSchedule(editingSchedule.id, {
//         name,
//         access_start_time: startTime,
//         access_end_time: endTime,
//         applies_to_weekdays: weekdays,
//         applies_to_weekends: weekends,
//         specific_dates: specificDates ? specificDates.split(",") : null,
//       });
//       setSchedules((prev) =>
//         prev.map((s) => (s.id === editingSchedule.id ? updated : s))
//       );
//       resetForm();
//       setEditingSchedule(null);
//     } catch (err) {
//       console.error(err);
//     }
//   };

//   const handleDelete = async (id: number) => {
//     try {
//       await deleteSchedule(id);
//       setSchedules((prev) => prev.filter((s) => s.id !== id));
//     } catch (err) {
//       console.error(err);
//     }
//   };

//   const filteredSchedules = schedules.filter((s) =>
//     s.name.toLowerCase().includes(search.toLowerCase())
//   );

//   if (loading)
//     return (
//       <DashboardLayout>
//         <p>Loading schedules...</p>
//       </DashboardLayout>
//     );

//   return (
//     <DashboardLayout>
//       <div className="space-y-6">

//         {/* Add / Update Form */}
//         <Card className="p-4 mb-6 shadow-card border-border">
//           <CardHeader>
//             <CardTitle>{editingSchedule ? "Update Schedule" : "Add Schedule"}</CardTitle>
//           </CardHeader>
//           <CardContent className="flex flex-col md:flex-row gap-2 flex-wrap items-center">
//             <Input placeholder="Schedule Name" value={name} onChange={e => setName(e.target.value)} />

//             <Label>Start Time</Label>
//             <Input type="time" value={startTime} onChange={e => setStartTime(e.target.value)} />

//             <Label>End Time</Label>
//             <Input type="time" value={endTime} onChange={e => setEndTime(e.target.value)} />

//             <label className="flex items-center gap-2">
//               <input type="checkbox" checked={weekdays} onChange={e => setWeekdays(e.target.checked)} />
//               Applies to Weekdays
//             </label>

//             <label className="flex items-center gap-2">
//               <input type="checkbox" checked={weekends} onChange={e => setWeekends(e.target.checked)} />
//               Applies to Weekends
//             </label>

//             <Input
//               placeholder="Specific Dates (comma separated: YYYY-MM-DD)"
//               value={specificDates}
//               onChange={e => setSpecificDates(e.target.value)}
//             />

//             {editingSchedule ? (
//               <>
//                 <Button onClick={handleUpdateSubmit}>Save</Button>
//                 <Button variant="outline" onClick={() => { resetForm(); setEditingSchedule(null); }}>Cancel</Button>
//               </>
//             ) : (
//               <Button onClick={handleAdd}>Add</Button>
//             )}
//           </CardContent>
//         </Card>

//         {/* Header with Search & View Toggle */}
//         <div className="flex items-center justify-between">
//           <div className="flex-1 relative">
//             <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
//             <Input
//               placeholder="Search schedules..."
//               className="pl-10 bg-secondary border-border"
//               value={search}
//               onChange={(e) => setSearch(e.target.value)}
//             />
//           </div>
//           <div className="flex gap-2 ml-4">
//             <Button variant={viewMode === "grid" ? "default" : "outline"} size="icon" onClick={() => setViewMode("grid")}><Grid3x3 className="w-4 h-4" /></Button>
//             <Button variant={viewMode === "list" ? "default" : "outline"} size="icon" onClick={() => setViewMode("list")}><List className="w-4 h-4" /></Button>
//           </div>
//         </div>

//         {/* Schedules Tabs */}
//         <Card className="shadow-card border-border">
//           <CardContent>
//             <Tabs defaultValue="all">
//               <TabsList className="bg-secondary mb-6">
//                 <TabsTrigger value="all">All ({filteredSchedules.length})</TabsTrigger>
//               </TabsList>

//               <TabsContent value="all">
//                 <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-4"}>
//                   {filteredSchedules.map((s) => (
//                     <Card key={s.id} className="shadow-card border-border p-4">
//                       <div className="mb-2 font-bold text-lg">{s.name}</div>
//                       <div className="flex flex-wrap gap-2 mb-2">
//                         <Badge>Start: {s.access_start_time}</Badge>
//                         <Badge>End: {s.access_end_time}</Badge>
//                         {s.applies_to_weekdays && <Badge variant="secondary">Weekdays</Badge>}
//                         {s.applies_to_weekends && <Badge variant="destructive">Weekends</Badge>}
//                         {s.specific_dates?.length ? <Badge variant="outline">Specific: {s.specific_dates.join(", ")}</Badge> : null}
//                       </div>
//                       <div className="flex gap-2 justify-end">
//                         <Button size="sm" onClick={() => handleEditClick(s)}><Edit className="w-3 h-3 mr-1 inline" />Edit</Button>
//                         <Button size="sm" variant="outline" onClick={() => handleDelete(s.id)}><Trash className="w-3 h-3 mr-1 inline" />Delete</Button>
//                       </div>
//                     </Card>
//                   ))}
//                 </div>
//               </TabsContent>
//             </Tabs>
//           </CardContent>
//         </Card>

//       </div>
//     </DashboardLayout>
//   );
// }